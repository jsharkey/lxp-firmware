#!/usr/bin/env python3
"""
A black-box battery BMS on the other end of CAN1 -- the inverter's "battery BMS
CAN bus" (docs/16, docs/20). It lets a test inject the CAN telemetry frames the
real pack transmits (SOC/SOH, limits, measurements) and let the firmware image's
own CAN1 receive path pick them up, exactly as it would on the bus.

It names no firmware symbol and pokes no internal RAM, so it is usable from the
*common* tests against any image that reads the pack over CAN1.

How it drives CAN1 without modifying tools/arm_sim.py: it models just enough of
the STM32 bxCAN *receive FIFO 0* -- the registers a polled reader touches -- by
hooking them through the sim's `uc` handle. While a frame is queued it reports
one message pending in RF0R and presents that frame in the FIFO mailbox
(identifier / length / data registers); when the firmware releases the FIFO
(RFOM0) it pops to the next. docs/20 records that the com-MCU polls CAN1 (no
IRQ), so a polled reader is the path this models. (bxCAN has no RX interrupt
fired here, and our firmware has no CAN reader yet -- so this is scaffolding that
runs red until the ARM battery-telemetry path exists.)

Frame layouts: include/inv/bms_can_map.h. 0x355 SOC/SOH is DLC 6, little-endian:
[0:1] SOC %, [2:3] SOH %, [4:5] SOC high-res (x0.01 %).
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

# bxCAN CAN1 (STM32F103, remapped to PB8/PB9 per docs/16; the register base is
# fixed regardless of the pin remap).
CAN1   = 0x40006400
CAN_RF0R = CAN1 + 0x00C        # receive FIFO 0: FMP0[1:0] pending, RFOM0 bit5 release
# FIFO 0 mailbox:
CAN_RI0R  = CAN1 + 0x1B0       # identifier: STID[31:21], IDE bit2, RTR bit1
CAN_RDT0R = CAN1 + 0x1B4       # DLC[3:0], FMI[15:8], TIME[31:16]
CAN_RDL0R = CAN1 + 0x1B8       # data bytes 0..3 (little-endian)
CAN_RDH0R = CAN1 + 0x1BC       # data bytes 4..7 (little-endian)
RF0R_RFOM0 = 1 << 5

# Battery -> inverter telemetry IDs we can stand in for (bms_can_map.h).
CAN_ID_SOC_SOH = 0x355


class CanBattery:
    """Stand-in for the pack on CAN1. Construct it on a sim (before the image is
    run) and queue frames with send()/send_soc_soh(); the firmware's own CAN1
    poll loop consumes them."""

    def __init__(self, sim):
        self.sim = sim
        self._rx = []              # queued frames to the ARM: (can_id, data bytes)
        self._install_hooks()

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

    def _install_hooks(self):
        uc = self.sim.uc

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
            return True

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

    def send_soc_soh(self, soc, soh, soc_hires=None):
        """Queue a 0x355 SOC/SOH telemetry frame (percent values)."""
        if soc_hires is None:
            soc_hires = soc * 100
        self.send(CAN_ID_SOC_SOH, struct.pack("<HHH", soc, soh, soc_hires))
