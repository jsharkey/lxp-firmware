#!/usr/bin/env python3
"""
A black-box battery BMS on the other end of CAN1 -- the inverter's "battery BMS
CAN bus" (docs/16, docs/20). It lets a test inject the CAN telemetry frames the
real pack transmits (SOC/SOH, limits, measurements) and let the firmware image's
own CAN1 receive path pick them up, exactly as it would on the bus.

It names no firmware symbol and pokes no internal RAM, so it is usable from the
*common* tests against any image that reads the pack over CAN1.

How it drives CAN1 without modifying tools/arm_sim.py: it models the STM32 bxCAN
*receive FIFO 0* -- the registers a reader touches -- by hooking them through the
sim's `uc` handle. While a frame is queued it reports one message pending in RF0R
and presents that frame in the FIFO mailbox (identifier / length / data); when
the firmware releases the FIFO (RFOM0) it pops to the next.

Polled vs interrupt-driven, as one black box (mirrors the Modbus masters in
tests/arm_sim_modbus.py):
  * Our firmware polls CAN1 in its loop (`can_port_poll`, no FMPIE0), so the FIFO
    hooks above are all it needs.
  * The factory never polls: it enables the FIFO-0-message-pending interrupt
    (`CAN_IER` FMPIE0) and receives in the CAN1_RX0 ISR. So when a frame is
    queued and the firmware has armed FMPIE0, we pend CAN1_RX0 through the RTOS
    engine (sim.pend_irq) to run its ISR. A polled firmware arms nothing, so we
    never pend -- the same code drives both.
It also models the bxCAN init handshake the hardware provides (MSR INAK follows
MCR INRQ, SLAK follows SLEEP); without it the factory's CAN bring-up busy-waits
on MSR forever. Requires the sim to be under enable_rtos() for the IRQ path
(ModbusDongle already enables it); the MSR/FIFO hooks are harmless otherwise.

Frame layouts: include/inv/bms_can_map.h. 0x355 SOC/SOH is DLC 6, little-endian:
[0:1] SOC %, [2:3] SOH %, [4:5] SOC high-res (x0.01 %).
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

# bxCAN CAN1 (STM32F103, remapped to PB8/PB9 per docs/16; the register base is
# fixed regardless of the pin remap).
CAN1   = 0x40006400
CAN_MCR  = CAN1 + 0x000        # master control: INRQ bit0, SLEEP bit1
CAN_MSR  = CAN1 + 0x004        # master status:  INAK bit0, SLAK bit1
CAN_RF0R = CAN1 + 0x00C        # receive FIFO 0: FMP0[1:0] pending, RFOM0 bit5 release
CAN_IER  = CAN1 + 0x014        # interrupt enable: FMPIE0 bit1 (FIFO0 msg pending)
# FIFO 0 mailbox:
CAN_RI0R  = CAN1 + 0x1B0       # identifier: STID[31:21], IDE bit2, RTR bit1
CAN_RDT0R = CAN1 + 0x1B4       # DLC[3:0], FMI[15:8], TIME[31:16]
CAN_RDL0R = CAN1 + 0x1B8       # data bytes 0..3 (little-endian)
CAN_RDH0R = CAN1 + 0x1BC       # data bytes 4..7 (little-endian)
# TX status + the three TX mailboxes (for inverter->battery capture):
CAN_TSR  = CAN1 + 0x008        # transmit status: RQCPx/TXOKx low, TMEx (empty) bits 26-28
CAN_TX_MB = (CAN1 + 0x180, CAN1 + 0x190, CAN1 + 0x1A0)   # TIxR, +4 TDTxR, +8 TDLxR, +0xc TDHxR
TSR_TME_ALL  = 0x1C000000      # TME0|TME1|TME2 -> all three mailboxes free
TSR_DONE = (0x3, 0x300, 0x30000)  # per-mailbox RQCPx|TXOKx (transmit complete, OK)
TIR_TXRQ = 1 << 0              # TIxR transmit-mailbox request
MCR_INRQ   = 1 << 0
MCR_SLEEP  = 1 << 1
MSR_INAK   = 1 << 0
MSR_SLAK   = 1 << 1
RF0R_RFOM0 = 1 << 5
IER_FMPIE0 = 1 << 1
CAN1_RX0_VEC = 16 + 20         # NVIC USB_LP_CAN1_RX0 IRQn=20 -> exception vector 36

# Battery -> inverter telemetry IDs we can stand in for (bms_can_map.h).
CAN_ID_LIMITS  = 0x351        # charge/discharge V & I limits
CAN_ID_SOC_SOH = 0x355        # SOC / SOH
CAN_ID_VIT     = 0x356        # pack voltage / current / temperature
CAN_ID_ALARM_A = 0x359        # protection / alarm bitfields


class CanBattery:
    """Stand-in for the pack on CAN1. Construct it on a sim (before the image is
    run) and queue frames with send()/send_soc_soh(); the firmware's own CAN1
    receive path -- polled (ours) or interrupt-driven (the factory) -- consumes
    them."""

    def __init__(self, sim, capture_tx=False):
        self.sim = sim
        self._rx = []              # queued frames to the ARM: (can_id, data bytes)
        self.tx = []               # captured inverter->battery frames: (id, dlc, bytes)
        self._install_hooks()
        if capture_tx:
            self._install_tx_hooks()

    # -- bxCAN TX capture (inverter->battery), opt-in --------------------------
    def _install_tx_hooks(self):
        """Capture frames the firmware transmits on CAN1. Models the TX side the
        way _install_hooks models RX: present all three TX mailboxes as free (TSR
        TMEx) so a non-blocking sender proceeds, and on each TXRQ record the frame
        and report it sent (RQCPx/TXOKx). Needed for both images -- our firmware
        even drops the keep-alive unless TME0 reads set (can_port_send)."""
        uc = self.sim.uc

        def on_tsr_read(uc, access, addr, size, value, ud):
            cur = struct.unpack("<I", uc.mem_read(CAN_TSR, 4))[0]
            uc.mem_write(CAN_TSR, struct.pack("<I", cur | TSR_TME_ALL))
            return True

        def make_ti_write(i, base):
            def on_ti_write(uc, access, addr, size, value, ud):
                # Merge this write into the current TIxR so a 16-bit TXRQ write
                # (STID written separately, earlier) still yields the full id.
                old = struct.unpack("<I", uc.mem_read(base, 4))[0]
                shift = (addr - base) * 8
                mask = (((1 << (size * 8)) - 1) << shift) & 0xFFFFFFFF
                eff = (old & ~mask) | ((value << shift) & mask)
                if eff & TIR_TXRQ:
                    tdt = struct.unpack("<I", uc.mem_read(base + 4, 4))[0]
                    dl  = uc.mem_read(base + 8, 4)
                    dh  = uc.mem_read(base + 12, 4)
                    cid = (eff >> 3) if (eff & 0x4) else (eff >> 21) & 0x7FF  # ext : std
                    dlc = tdt & 0xF
                    self.tx.append((cid, dlc, bytes((bytes(dl) + bytes(dh))[:dlc])))
                    uc.mem_write(base, struct.pack("<I", eff & ~TIR_TXRQ))  # consume request
                    cur = struct.unpack("<I", uc.mem_read(CAN_TSR, 4))[0]
                    uc.mem_write(CAN_TSR, struct.pack("<I", cur | TSR_TME_ALL | TSR_DONE[i]))
                return True
            return on_ti_write

        uc.hook_add(UC_HOOK_MEM_READ, on_tsr_read, begin=CAN_TSR, end=CAN_TSR + 4)
        for i, base in enumerate(CAN_TX_MB):
            uc.hook_add(UC_HOOK_MEM_WRITE, make_ti_write(i, base), begin=base, end=base + 4)

    def tx_frames(self, can_id=None):
        """Captured TX frames (id, dlc, bytes), optionally filtered to one id."""
        return [f for f in self.tx if can_id is None or f[0] == can_id]

    # -- bxCAN RX FIFO0 glue (on top of arm_sim's peripheral hooks) ----------
    def _present_head(self, uc):
        """Mirror the head frame into the FIFO0 mailbox registers."""
        if not self._rx:
            return
        cid, data = self._rx[0]
        d = (bytes(data) + b"\x00" * 8)[:8]
        uc.mem_write(CAN_RI0R,  struct.pack("<I", (cid & 0x7FF) << 21))   # standard ID
        uc.mem_write(CAN_RDT0R, struct.pack("<I", len(data) & 0xF))       # DLC
        uc.mem_write(CAN_RDL0R, d[:4])
        uc.mem_write(CAN_RDH0R, d[4:8])

    def _set_fmp(self, uc):
        cur = struct.unpack("<I", uc.mem_read(CAN_RF0R, 4))[0]
        cur = (cur & ~0x3) | (min(len(self._rx), 3) & 0x3)   # FMP0 = pending count
        uc.mem_write(CAN_RF0R, struct.pack("<I", cur))

    def _armed(self):
        """True when the firmware has enabled the FIFO-0 RX interrupt (factory)."""
        return bool(self.sim.r32(CAN_IER) & IER_FMPIE0)

    def _maybe_pend(self):
        """Interrupt-driven RX: run the firmware's CAN1_RX0 ISR for a queued frame
        (no-op for a polled firmware, which leaves FMPIE0 clear)."""
        if self._rx and self._armed():
            self.sim.pend_irq(CAN1_RX0_VEC)

    def _install_hooks(self):
        uc = self.sim.uc

        def on_msr_read(uc, access, addr, size, value, ud):
            # Model the init handshake the hardware provides: INAK tracks INRQ,
            # SLAK tracks SLEEP. Without it the factory's CAN init spins on MSR.
            mcr = struct.unpack("<I", uc.mem_read(CAN_MCR, 4))[0]
            msr = struct.unpack("<I", uc.mem_read(CAN_MSR, 4))[0] & ~(MSR_INAK | MSR_SLAK)
            if mcr & MCR_INRQ:  msr |= MSR_INAK
            if mcr & MCR_SLEEP: msr |= MSR_SLAK
            uc.mem_write(CAN_MSR, struct.pack("<I", msr))
            return True

        def on_rf0r_read(uc, access, addr, size, value, ud):
            self._set_fmp(uc)
            self._present_head(uc)
            return True

        def on_rf0r_write(uc, access, addr, size, value, ud):
            # Firmware releases the mailbox by writing RFOM0 -> pop to next frame.
            if (value & RF0R_RFOM0) and self._rx:
                self._rx.pop(0)
                cur = struct.unpack("<I", uc.mem_read(CAN_RF0R, 4))[0] & ~RF0R_RFOM0
                uc.mem_write(CAN_RF0R, struct.pack("<I", cur))
                self._set_fmp(uc)
                self._present_head(uc)
                self._maybe_pend()          # more queued? re-assert the RX IRQ
            return True

        uc.hook_add(UC_HOOK_MEM_READ,  on_msr_read,  begin=CAN_MSR,  end=CAN_MSR + 4)
        uc.hook_add(UC_HOOK_MEM_READ,  on_rf0r_read,  begin=CAN_RF0R, end=CAN_RF0R + 4)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_rf0r_write, begin=CAN_RF0R, end=CAN_RF0R + 4)

    # -- queue frames --------------------------------------------------------
    def send(self, can_id, data):
        """Queue one classic 11-bit CAN frame (data: up to 8 bytes) for delivery."""
        assert len(data) <= 8
        self._rx.append((can_id & 0x7FF, bytes(data)))
        # keep FMP/mailbox current even if the firmware never reads RF0R first
        self._set_fmp(self.sim.uc)
        self._present_head(self.sim.uc)
        self._maybe_pend()                  # interrupt-driven RX: run its ISR

    def send_soc_soh(self, soc, soh, soc_hires=None):
        """Queue a 0x355 SOC/SOH telemetry frame (percent values)."""
        if soc_hires is None:
            soc_hires = soc * 100
        self.send(CAN_ID_SOC_SOH, struct.pack("<HHH", soc, soh, soc_hires))

    def send_measurements(self, voltage_cv, current_ca, temp_dc):
        """Queue a 0x356 V/I/T frame: voltage 0.01 V, current 0.01 A, temp
        0.1 degC (current and temp are signed)."""
        self.send(CAN_ID_VIT, struct.pack("<hhh", voltage_cv, current_ca, temp_dc))

    def send_limits(self, charge_volt_dv, charge_curr=0, discharge_curr=0,
                    discharge_volt_dv=0):
        """Queue a 0x351 limits frame: charge/discharge voltage 0.1 V, currents
        0.1 A (only the charge voltage limit is consumed so far)."""
        self.send(CAN_ID_LIMITS, struct.pack("<HHHH", charge_volt_dv, charge_curr,
                                             discharge_curr, discharge_volt_dv))

    def send_alarms(self, fault_bits, warn_bits, pack_count=1):
        """Queue a 0x359 protection/alarm frame: [0:1] protection bitfield,
        [2:3] alarm/warning bitfield, [4] module count, [5:6] the 'PN' marker."""
        self.send(CAN_ID_ALARM_A, struct.pack("<HHB", fault_bits, warn_bits,
                                              pack_count) + b"PN\x00")

    def settle(self, insn=6_000_000, chunk=1_000_000):
        """Run the firmware so injected telemetry propagates into its register
        image before a reader polls -- as a real monitor (polling at >=1 s) would
        see. Our firmware publishes synchronously in its loop, so this is a quick
        no-op-ish spin; the factory ingests in the CAN1_RX0 ISR and only publishes
        SOC/SOH once its periodic consumer task gets a scheduler slice, which this
        gives it. Needs the sim under enable_rtos() for the IRQ path (ModbusDongle
        enables it)."""
        done = 0
        while done < insn:
            self._maybe_pend()          # (re-)assert the RX IRQ if a frame waits
            self.sim.run(chunk)
            done += chunk
        return self
