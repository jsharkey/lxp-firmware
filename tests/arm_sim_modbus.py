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
byte the firmware transmitted. SysTick injection is enabled so the firmware's
millisecond time base advances (its RTU inter-frame gap and our poll loop both
need it).

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
SR_RXNE = 1 << 5           # read-data-register-not-empty

# Device defaults our firmware boots with (src/main.c). check_sn is off, so the
# SN is only echoed back, not matched -- any 10 bytes work as a stand-in.
DEFAULT_ADDR = 1
DEFAULT_SN   = b"0000000000"

FC_READ_HOLDING = 0x03
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
                 systick=20_000, boot_insn=1_200_000, txn_insn=2_000_000):
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
        sim.enable_systick(systick)
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
            return True

        def on_dr_write(uc, access, addr, size, value, ud):
            self._tx.append(value & 0xFF)
            # Stop as soon as our reply appears as a contiguous tail window (the
            # DSP push shares this UART, so count-based stopping won't do).
            if self._resp is None and self._rlen and len(self._tx) >= self._rlen:
                window = bytes(self._tx[-self._rlen:])
                if self._match(window):
                    self._resp = window
                    self.sim._halt = True      # break the SysTick chunk loop
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
        self.sim.run(self._txn_insn)        # resume the loop; hook stops on reply
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
        """Function 0x03. Returns a list of n register values, or None if no
        valid read-response frame was transmitted."""
        req = _frame(self.addr, FC_READ_HOLDING, struct.pack("<HH", reg, n), self.sn)

        def match(w):   # read response: addr func SN start nBytes data CRC
            return (w[0] == self.addr and w[1] == FC_READ_HOLDING and _crc_ok(w)
                    and w[_HDR + 2] == 2 * n)

        resp = self._txn(req, _HDR + 3 + 2 * n + _CRC, match)
        if resp is None:
            return None
        return [struct.unpack_from("<H", resp, _HDR + 3 + 2 * i)[0] for i in range(n)]
