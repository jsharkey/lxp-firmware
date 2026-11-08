#!/usr/bin/env python3
"""
Black-box Modbus-RTU "masters" that talk to a firmware image over one UART the
way a real peer would: frame a request, feed the bytes in on that UART, let the
firmware's own loop/ISR parse them and transmit a reply, and capture that reply.

Two masters, one per physical link -- pick the one that matches the port the
image actually serves; there is **no auto-detection**:

  * ModbusDongle -- the external RS-485 datalogger on **UART5** (`0x40005000`).
    This is where the dongle is hard-wired on the board and where the ARM is the
    Modbus *slave* (docs/26, docs/wiring/ARM-UART5-dongle). **Our firmware serves
    the dongle here**, so use this for ours.
  * ModbusDsp    -- the ARM↔DSP link on **USART3** (`0x40004800`), where the DSP
    polls the ARM as a Modbus master. In this harness that is the port the
    *factory* image answers register reads/writes on: its real UART5 dongle RX is
    a scheduler task that never gets the CPU without the RTOS running (T02), while
    the USART3 slave path is the NVIC-vectored ISR we can drive. The register
    model served there is the same one the dongle reads, so it is a valid
    register oracle for the factory meanwhile. (Do NOT point this at UART5 on the
    factory: its UART5 ISR consumes a request and disturbs the config flash.)

Both share one implementation (`_ModbusMaster`); they differ only in the UART
base + IRQ vector. Each instance exposes `.base/.sr/.dr/.cr1/.vec` for callers
that hand-roll a transaction (e.g. settings_contract.py).

How it drives a UART without modifying tools/arm_sim.py: Unicorn hooks on that
UART's data/status registers. On a status read it raises RXNE while a request
byte is queued; on a data read it hands over the next byte; on a data write it
captures the transmitted byte. A polled firmware reads SR/DR from its loop; an
interrupt-driven one (RXNEIE/TXEIE armed) is serviced by pending that UART's IRQ
through the RTOS engine (sim.pend_irq). The same code drives both.

USART3 also carries the DSP config push, so that port's TX stream is a mix; we
stop and extract on the first *contiguous, valid* Modbus response frame that
matches the request (right address, function code, CRC). DSP frames use address 0
and a different shape, so they never match.

Framing (EG4 18kPV-12LV family, little-endian on the wire, CRC-16/MODBUS):
    request  0x06 write1 : addr func SN[10] regLo regHi valLo valHi      CRC
    request  0x03 readN  : addr func SN[10] startLo startHi numLo numHi  CRC
    response 0x03 readN  : addr func SN[10] startLo startHi nBytes v*2N   CRC
See include/inv/modbus.h.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

SR_RXNE    = 1 << 5        # status: read-data-register-not-empty
CR1_RXNEIE = 1 << 5        # control: RX-not-empty interrupt enable
CR1_TXEIE  = 1 << 7        # control: TX-empty interrupt enable
_TXN_CHUNK = 40_000        # instructions per step while driving a transaction

# UART5 = the dongle port; USART3 = the ARM↔DSP link. IRQn + 16 = exception vector.
UART5_BASE,  UART5_VEC  = 0x40005000, 16 + 53
USART3_BASE, USART3_VEC = 0x40004800, 16 + 39

# Device defaults our firmware boots with (src/main.c). check_sn is off, so the
# SN is only echoed back, not matched -- any 10 bytes work as a stand-in.
DEFAULT_ADDR = 1
DEFAULT_SN   = b"0000000000"

FC_READ_HOLDING = 0x03
FC_READ_INPUT   = 0x04
FC_WRITE_SINGLE = 0x06
FC_WRITE_MULTI  = 0x10
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


def _scan_reply(tx, addr, func, n):
    """Scan a captured TX byte stream for this request's reply (used by the whole-
    surface sweep, T23). Returns one of:
      ("ok", [v0..v(n-1)])  -- a valid func read-response for n registers
      ("exc", code)         -- a Modbus exception (func|0x80) with its code
      None                  -- nothing valid seen yet
    A read-response is  addr func SN[10] start(2) nBytes(=2n) data(2n) CRC; an
    exception is the short addr func|0x80 ... code CRC frame (len 5..20)."""
    i, N = 0, len(tx)
    resp_len = _HDR + 3 + 2 * n + _CRC
    while i < N - 4:
        if tx[i] == addr:
            f1 = tx[i + 1]
            if f1 == func and i + resp_len <= N:
                fr = bytes(tx[i:i + resp_len])
                if fr[_HDR + 2] == 2 * n and _crc_ok(fr):
                    return ("ok", [struct.unpack_from("<H", fr, _HDR + 3 + 2 * k)[0]
                                   for k in range(n)])
            if f1 == (func | 0x80):
                for ln in range(5, 21):
                    if i + ln <= N:
                        fr = bytes(tx[i:i + ln])
                        if crc16(fr[:-2]) == (fr[-2] | (fr[-1] << 8)):
                            return ("exc", fr[-3])
        i += 1
    return None


class _ModbusMaster:
    """Drive `sim` (an already-constructed ArmSim) as a Modbus master on ONE
    UART. Boots the image into its main loop on construction; then
    write_single()/read_holding()/read_input() perform one transaction each.
    Subclasses set PORT_BASE/PORT_VEC/PORT_NAME; use ModbusDongle or ModbusDsp."""

    PORT_NAME = "?"
    PORT_BASE = 0
    PORT_VEC  = 0

    def __init__(self, sim, addr=DEFAULT_ADDR, sn=DEFAULT_SN,
                 systick=20_000, boot_insn=4_000_000, txn_insn=4_000_000):
        # boot_insn covers the full power-on path before the main loop services
        # Modbus (our firmware paints a boot splash on the real LCD -- millions of
        # emulated instructions; 4M boots both images with margin).
        self.sim = sim
        self.addr = addr
        self.sn = bytes(sn)
        self._txn_insn = txn_insn
        self.base = self.PORT_BASE
        self.vec  = self.PORT_VEC
        self.sr   = self.base + 0x00
        self.dr   = self.base + 0x04
        self.cr1  = self.base + 0x0C
        self._rx = []              # request bytes still to hand to the firmware
        self._tx = bytearray()     # bytes the firmware has transmitted
        self._rlen = 0             # expected response length (tail window to test)
        self._match = None         # validator(window) -> True when it's our reply
        self._resp = None          # the extracted response frame, once seen
        self._install_hooks()
        # The factory boots only with a valid config flash (docs/21); provide one
        # unless the caller already attached an SPI device. Inert for our image.
        if getattr(sim, "spi_flash", None) is None:
            sim.attach_config_flash()
        # Use the exception engine, not plain SysTick injection: an interrupt-driven
        # UART (RX and TX) needs the IRQ delivered (sim.pend_irq); the engine also
        # runs the factory's RTOS. A polled firmware is unaffected.
        sim.enable_rtos(systick)
        sim.run_reset(max_insn=boot_insn)   # boot through init into the loop

    # -- UART glue (added on top of arm_sim's own peripheral hooks) ----------
    def _install_hooks(self):
        uc = self.sim.uc

        def on_sr_read(uc, access, addr, size, value, ud):
            # arm_sim already forced SR=TXE|TC here; add RXNE while a byte waits.
            if self._rx:
                cur = struct.unpack("<I", uc.mem_read(self.sr, 4))[0]
                uc.mem_write(self.sr, struct.pack("<I", cur | SR_RXNE))
            return True

        def on_dr_read(uc, access, addr, size, value, ud):
            if self._rx:
                uc.mem_write(self.dr, struct.pack("<I", self._rx.pop(0)))
                # Re-pend while bytes remain so an interrupt-driven RX delivers
                # them back-to-back (idempotent; a polled RX ignores it).
                if self._rx and (self.sim.r32(self.cr1) & CR1_RXNEIE):
                    self.sim.pend_irq(self.vec)
            return True

        def on_dr_write(uc, access, addr, size, value, ud):
            self._tx.append(value & 0xFF)
            if self.sim.r32(self.cr1) & CR1_TXEIE:
                self.sim.pend_irq(self.vec)     # TX ISR: re-pend to drain the reply
            # Stop as soon as our reply appears as a contiguous tail window.
            if self._resp is None and self._rlen and len(self._tx) >= self._rlen:
                window = bytes(self._tx[-self._rlen:])
                if self._match(window):
                    self._resp = window
                    self.sim._halt = True       # break the run-chunk loop
                    uc.emu_stop()
            return True

        uc.hook_add(UC_HOOK_MEM_READ,  on_sr_read, begin=self.sr, end=self.sr + 4)
        uc.hook_add(UC_HOOK_MEM_READ,  on_dr_read, begin=self.dr, end=self.dr + 4)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_dr_write, begin=self.dr, end=self.dr + 4)

    # -- one request/response transaction ------------------------------------
    def _txn(self, request, rlen, match):
        self._rx = list(request)
        self._tx = bytearray()
        self._rlen = rlen
        self._match = match
        self._resp = None
        remaining = self._txn_insn
        while self._resp is None and remaining > 0:
            cr1 = self.sim.r32(self.cr1)
            if (cr1 & CR1_RXNEIE and self._rx) or (cr1 & CR1_TXEIE):
                self.sim.pend_irq(self.vec)
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

    def write_multiple(self, start, values):
        """Function 0x10 (write-multiple). `values` is a list of u16. Per the EG4
        spec this is only valid for the SN (HR 2-6) and time (HR 12-14) blocks.
        Returns the register count the device echoed, or None if no valid echo."""
        n = len(values)
        body = struct.pack("<HHB", start, n, 2 * n) + b"".join(struct.pack("<H", v) for v in values)
        req = _frame(self.addr, FC_WRITE_MULTI, body, self.sn)

        def match(w):   # echo frame: addr func SN start count CRC
            return (w[0] == self.addr and w[1] == FC_WRITE_MULTI and _crc_ok(w)
                    and struct.unpack_from("<H", w, _HDR)[0] == start)

        resp = self._txn(req, _HDR + 4 + _CRC, match)
        return None if resp is None else struct.unpack_from("<H", resp, _HDR + 2)[0]

    def write_sn(self, sn10):
        """Set the 10-byte device serial number via a 0x10 write to HR 2-6
        (2 ASCII bytes per register, little-endian within each)."""
        sn10 = bytes(sn10)
        assert len(sn10) == 10
        regs = [sn10[2 * i] | (sn10[2 * i + 1] << 8) for i in range(5)]
        return self.write_multiple(2, regs)

    def read_sn(self):
        """Read the 10-byte SN back from HR 2-6; returns bytes or None."""
        regs = self.read_holding(2, 5)
        if regs is None:
            return None
        return bytes(b for r in regs for b in (r & 0xFF, (r >> 8) & 0xFF))

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

    def probe_read(self, func, reg, n):
        """Like read_*, but classifies the reply for the whole-surface sweep (T23):
        returns ("ok", [values]) | ("exc", code) | ("silent",). Stops as soon as a
        reply (response OR exception) appears, so out-of-map reads are not slow."""
        req = _frame(self.addr, func, struct.pack("<HH", reg, n), self.sn)
        self._rx = list(req)
        self._tx = bytearray()
        self._rlen = 0
        self._match = lambda w: False        # don't early-stop in the hook; we scan
        self._resp = None
        remaining = self._txn_insn
        while remaining > 0:
            cr1 = self.sim.r32(self.cr1)
            if (cr1 & CR1_RXNEIE and self._rx) or (cr1 & CR1_TXEIE):
                self.sim.pend_irq(self.vec)
            self.sim.run(_TXN_CHUNK)
            remaining -= _TXN_CHUNK
            r = _scan_reply(self._tx, self.addr, func, n)
            if r is not None:
                return r
        return ("silent",)


class ModbusDongle(_ModbusMaster):
    """The external RS-485 datalogger on **UART5** (the board's hard-wired dongle
    port; the ARM is the slave). Use this for our firmware."""
    PORT_NAME, PORT_BASE, PORT_VEC = "UART5", UART5_BASE, UART5_VEC


class ModbusDsp(_ModbusMaster):
    """The ARM↔DSP link on **USART3**, where the DSP polls the ARM as a Modbus
    master. In this harness it is the factory image's reachable register-slave
    port (its UART5 dongle RX is a scheduler task that needs the RTOS, T02)."""
    PORT_NAME, PORT_BASE, PORT_VEC = "USART3", USART3_BASE, USART3_VEC
