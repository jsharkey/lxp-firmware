#!/usr/bin/env python3
"""
A black-box Modbus-RTU "dongle" that talks to the firmware image over USART3 --
the RS485/dongle link (docs/04, docs/16) -- the same way a real monitoring tool
would: it frames a request, feeds the bytes in on the UART, lets the firmware's
own loop parse them and transmit a reply, and captures that reply off the UART.

It names no firmware symbol and poke no internal RAM, so it is usable from the
*common* tests against any image that speaks the EG4 Modbus dongle protocol.

How it drives the UART without modifying tools/arm_sim.py: it adds its own
Unicorn hooks on the USART3 data/status registers through the sim's `uc`
handle. On a status read it raises RXNE while a request byte is queued; on a
data read it hands over the next queued byte; on a data write it captures the
byte the firmware transmitted.

Polled vs interrupt-driven, as one black box: our firmware polls USART3 in its
loop (CR1 has neither RXNEIE nor TXEIE), so the hooks above are all it needs.
The factory never polls -- it receives on the USART3 RX interrupt and transmits
from the TX interrupt. So the transaction loop watches CR1: whenever the firmware
has armed an interrupt (RXNEIE with a byte queued, or TXEIE), it delivers the
USART3 IRQ via the RTOS engine (sim.pend_irq), running the firmware's own ISR to
take a byte or emit one. A polled firmware arms neither, so nothing is pended --
the same code drives both. (This is why it runs under enable_rtos, not plain
SysTick injection; the engine also boots the factory's RTOS, and SysTick still
advances the firmware's ms time base for RTU framing.)

USART3 currently carries the DSP config push as well as the dongle Modbus (a
known placeholder collision -- see src/dsp/dsp_link_port.c), so the captured TX
stream is a mix. We therefore stop and extract on the first *contiguous, valid*
Modbus response frame that matches the request (right address, function code and
CRC); the DSP frames use address 0 and a different shape, so they never match.

Framing (EG4 18kPV-12LV family, little-endian on the wire, CRC-16/MODBUS):
    request  0x06 write1 : addr func SN[10] regLo regHi valLo valHi      CRC
    request  0x03 readN  : addr func SN[10] startLo startHi numLo numHi  CRC
    response 0x03 readN  : addr func SN[10] startLo startHi nBytes v*2N   CRC
See include/inv/modbus.h.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

# USART3 (the one NVIC-vectored UART; our mb_port_init configures it) -----
USART3 = 0x40004800
MB_SR  = USART3 + 0x00     # status register
MB_DR  = USART3 + 0x04     # data register
MB_CR1 = USART3 + 0x0C     # control register 1
SR_RXNE = 1 << 5           # read-data-register-not-empty
CR1_RXNEIE = 1 << 5        # RX-not-empty interrupt enable
CR1_TXEIE  = 1 << 7        # TX-empty interrupt enable
USART3_VEC = 16 + 39       # NVIC USART3_IRQn=39 -> exception vector 55 (both images)
_TXN_CHUNK = 40_000        # instructions per step while driving a transaction

# Device defaults our firmware boots with (src/main.c). check_sn is off, so the
# SN is only echoed back, not matched -- any 10 bytes work as a stand-in.
DEFAULT_ADDR = 1
DEFAULT_SN   = b"0000000000"

FC_READ_HOLDING = 0x03
FC_READ_INPUT   = 0x04
FC_WRITE_SINGLE = 0x06
_SN_LEN   = 10
_HDR      = 2 + _SN_LEN             # addr + func + SN, before the body
_CRC      = 2


def crc16(buf):
    """Modbus CRC-16 (poly 0xA001, init 0xFFFF) -- matches inv_modbus_crc16()."""
    crc = 0xFFFF
    for b in buf:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def _frame(addr, func, body, sn):
    f = bytes([addr, func]) + bytes(sn) + bytes(body)
    c = crc16(f)
    return f + bytes([c & 0xFF, (c >> 8) & 0xFF])


def _crc_ok(resp):
    return len(resp) >= _HDR + _CRC and \
        crc16(resp[:-2]) == (resp[-2] | (resp[-1] << 8))


class ModbusDongle:
    """Drive `sim` (an already-constructed ArmSim) as a Modbus master. Boots the
    image into its main loop on construction; then write_single()/read_holding()
    perform one request/response transaction each."""

    def __init__(self, sim, addr=DEFAULT_ADDR, sn=DEFAULT_SN,
                 systick=20_000, boot_insn=4_000_000, txn_insn=4_000_000):
        # boot_insn covers the full power-on path before the main loop services
        # Modbus. Our firmware paints a boot splash on the real LCD (a bit-banged
        # TFT, ~millions of emulated instructions), so 1M was too tight and left
        # the first request unanswered; 4M boots both images with margin (the
        # factory, which boots faster, just idles the remainder).
        self.sim = sim
        self.addr = addr
        self.sn = bytes(sn)
        self._txn_insn = txn_insn
        self._rx = []              # request bytes still to hand to the firmware
        self._tx = bytearray()     # bytes the firmware has transmitted
        self._rlen = 0             # expected response length (tail window to test)
        self._match = None         # validator(window) -> True when it's our reply
        self._resp = None          # the extracted response frame, once seen
        self._install_hooks()
        # The factory boots only with a valid config flash (docs/21); provide one
        # unless the caller already attached an SPI device. Inert for images that
        # don't use the config flash (e.g. our firmware).
        if getattr(sim, "spi_flash", None) is None:
            sim.attach_config_flash()
        # Use the exception engine, not plain SysTick injection: the factory's
        # dongle UART is interrupt-driven (RX and TX), so the transaction loop
        # must be able to deliver the USART3 IRQ (sim.pend_irq); the engine also
        # runs the factory's RTOS. A polled firmware (ours) is unaffected.
        sim.enable_rtos(systick)
        sim.run_reset(max_insn=boot_insn)   # boot through init into the loop

    # -- UART glue (added on top of arm_sim's own peripheral hooks) ----------
    def _install_hooks(self):
        uc = self.sim.uc

        def on_sr_read(uc, access, addr, size, value, ud):
            # arm_sim already forced SR=TXE|TC here; add RXNE while a byte waits.
            if self._rx:
                cur = struct.unpack("<I", uc.mem_read(MB_SR, 4))[0]
                uc.mem_write(MB_SR, struct.pack("<I", cur | SR_RXNE))
            return True

        def on_dr_read(uc, access, addr, size, value, ud):
            if self._rx:
                uc.mem_write(MB_DR, struct.pack("<I", self._rx.pop(0)))
                # Interrupt-driven RX: while bytes remain, re-pend the IRQ so the
                # ISR runs again immediately -- bytes are delivered back-to-back
                # instead of one per run-chunk, which is most of the speed-up. An
                # ISR that takes one byte per interrupt gets one re-pend per byte;
                # a drain-all ISR re-pends per byte too but pend_irq is idempotent,
                # so it collapses to a single (harmless) extra delivery. (A polled
                # firmware reads DR from its loop with RXNEIE clear -> no pend.)
                if self._rx and (self.sim.r32(MB_CR1) & CR1_RXNEIE):
                    self.sim.pend_irq(USART3_VEC)
            return True

        def on_dr_write(uc, access, addr, size, value, ud):
            self._tx.append(value & 0xFF)
            # Interrupt-driven TX: the ISR writes one byte per TXE IRQ; while it
            # still wants to send (TXEIE set), re-pend so the rest of the reply
            # drains back-to-back.
            if self.sim.r32(MB_CR1) & CR1_TXEIE:
                self.sim.pend_irq(USART3_VEC)
            # Stop as soon as our reply appears as a contiguous tail window (the
            # DSP push shares this UART, so count-based stopping won't do).
            if self._resp is None and self._rlen and len(self._tx) >= self._rlen:
                window = bytes(self._tx[-self._rlen:])
                if self._match(window):
                    self._resp = window
                    self.sim._halt = True      # break the run-chunk loop
                    uc.emu_stop()
            return True

        uc.hook_add(UC_HOOK_MEM_READ,  on_sr_read, begin=MB_SR, end=MB_SR + 4)
        uc.hook_add(UC_HOOK_MEM_READ,  on_dr_read, begin=MB_DR, end=MB_DR + 4)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_dr_write, begin=MB_DR, end=MB_DR + 4)

    # -- one request/response transaction ------------------------------------
    def _txn(self, request, rlen, match):
        self._rx = list(request)
        self._tx = bytearray()
        self._rlen = rlen
        self._match = match
        self._resp = None
        remaining = self._txn_insn
        while self._resp is None and remaining > 0:
            # Interrupt-driven firmware (the factory) receives on the USART3 RX
            # IRQ and transmits from its TX IRQ -- it never polls. When it has
            # armed either (CR1.RXNEIE with a byte still queued, or CR1.TXEIE),
            # deliver that IRQ through the RTOS engine so its ISR runs. A polled
            # firmware (ours) arms neither, so we never pend and its own SR/DR
            # polling -- serviced by the hooks below -- drives the exchange.
            cr1 = self.sim.r32(MB_CR1)
            if (cr1 & CR1_RXNEIE and self._rx) or (cr1 & CR1_TXEIE):
                self.sim.pend_irq(USART3_VEC)
            self.sim.run(_TXN_CHUNK)        # resume; on_dr_write stops us on a reply
            remaining -= _TXN_CHUNK
        return self._resp

    def write_single(self, reg, val):
        """Function 0x06. Returns the value the device echoed, or None if no
        valid echo frame was transmitted."""
        req = _frame(self.addr, FC_WRITE_SINGLE, struct.pack("<HH", reg, val), self.sn)

        def match(w):   # echo frame: addr func SN reg val CRC
            return (w[0] == self.addr and w[1] == FC_WRITE_SINGLE and _crc_ok(w)
                    and struct.unpack_from("<H", w, _HDR)[0] == reg)

        resp = self._txn(req, _HDR + 4 + _CRC, match)
        return None if resp is None else struct.unpack_from("<H", resp, _HDR + 2)[0]

    def read_holding(self, reg, n=1):
        """Function 0x03 (holding registers). Returns a list of n register
        values, or None if no valid read-response frame was transmitted."""
        return self._read(FC_READ_HOLDING, reg, n)

    def read_input(self, reg, n=1):
        """Function 0x04 (input registers, e.g. IR_SOC_SOH = 5). Returns a list
        of n register values, or None if no valid response frame was sent."""
        return self._read(FC_READ_INPUT, reg, n)

    def _read(self, func, reg, n):
        # 0x03 and 0x04 share the response layout (addr func SN start nBytes data CRC).
        req = _frame(self.addr, func, struct.pack("<HH", reg, n), self.sn)

        def match(w):
            return (w[0] == self.addr and w[1] == func and _crc_ok(w)
                    and w[_HDR + 2] == 2 * n)

        resp = self._txn(req, _HDR + 3 + 2 * n + _CRC, match)
        if resp is None:
            return None
        return [struct.unpack_from("<H", resp, _HDR + 3 + 2 * i)[0] for i in range(n)]
