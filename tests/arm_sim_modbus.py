#!/usr/bin/env python3
"""
A black-box Modbus-RTU "dongle" that talks to the firmware image over its
external RS-485 port the way a real monitoring datalogger would: it frames a
request, feeds the bytes in on the UART, lets the firmware's own loop/ISR parse
them and transmit a reply, and captures that reply off the UART.

It names no firmware symbol and pokes no internal RAM, so it is usable from the
*common* tests against any image that speaks the EG4 Modbus dongle protocol.

Which UART? (T01 / docs/26 / docs/wiring/ARM-UART5-dongle). The factory's external
dongle port is **UART5** (`0x40005000`), where the ARM is the Modbus *slave* —
USART3 is the ARM↔DSP link (the ARM is the master there). Our firmware now serves
the dongle on UART5 too (`src/modbus/modbus_port.c`). But in *this* harness the
factory only answers on **USART3**: its UART5 receive path is a scheduler task
that never gets the CPU without the RTOS running (T02), whereas the USART3 slave
path is the NVIC-vectored ISR we can drive. The USART3 register model the factory
serves there is the same one the dongle reads, so it is a valid register oracle
until T02 lands. (Proven: feeding a read on UART5 draws no reply from the factory;
on USART3 it does.)

So the dongle **auto-detects** the port: it tries UART5 first (ours answers), and
falls back to USART3 (the factory answers). Each port is driven one at a time —
driving both at once is unsafe because the factory's UART5 ISR consumes the bytes
without replying, starving the USART3 path. Once a port answers it is latched.

How it drives a UART without modifying tools/arm_sim.py: it adds Unicorn hooks on
that UART's data/status registers. On a status read it raises RXNE while a request
byte is queued; on a data read it hands over the next queued byte; on a data write
it captures the transmitted byte. A polled firmware reads SR/DR from its loop; an
interrupt-driven one (RXNEIE/TXEIE armed) is serviced by pending that UART's IRQ
through the RTOS engine (sim.pend_irq). The same code drives both.

USART3 also carries the DSP push, so that port's TX stream is a mix; we stop and
extract on the first *contiguous, valid* Modbus response frame that matches the
request (right address, function code, CRC). DSP frames use address 0 and a
different shape, so they never match.

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

# The candidate dongle ports. Each: (name, base, exception-vector).
#   UART5  0x40005000, IRQ 53 -> exception vector 69  (ours; factory's real port)
#   USART3 0x40004800, IRQ 39 -> exception vector 55  (factory's reachable slave)
PORT_UART5  = ("UART5",  0x40005000, 16 + 53)
PORT_USART3 = ("USART3", 0x40004800, 16 + 39)
# Detection order is USART3 THEN UART5, deliberately: probing UART5 on the factory
# has a side effect (its UART5 ISR consumes the request and disturbs the config
# flash/persistence), so we must never probe the factory's UART5. The factory
# answers on USART3, so it latches there before UART5 is ever tried. Our firmware
# does not serve Modbus on USART3 (that port is the DSP link, TX-only, no RX IRQ),
# so the USART3 probe is inert for ours and detection falls through to UART5.
DEFAULT_PORTS = [PORT_USART3, PORT_UART5]

_TXN_CHUNK   = 40_000      # instructions per step while driving a transaction
_PROBE_GRACE = 1_000_000   # bail a detection probe if the port's DR is never read

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
    perform one request/response transaction each, over whichever port the image
    answers on (auto-detected: UART5 first, USART3 fallback)."""

    def __init__(self, sim, addr=DEFAULT_ADDR, sn=DEFAULT_SN,
                 systick=20_000, boot_insn=4_000_000, txn_insn=4_000_000,
                 ports=None):
        # boot_insn covers the full power-on path before the main loop services
        # Modbus (our firmware paints a boot splash on the real LCD -- millions of
        # emulated instructions; 4M boots both images with margin).
        self.sim = sim
        self.addr = addr
        self.sn = bytes(sn)
        self._txn_insn = txn_insn
        self._ports = list(ports) if ports else list(DEFAULT_PORTS)
        self._port = self._ports[0] if len(self._ports) == 1 else None  # latched
        self._rx = []              # request bytes still to hand to the firmware
        self._tx = {}              # per-port captured TX: name -> bytearray
        self._cur = None           # name of the port currently being driven
        self._rlen = 0             # expected response length (tail window to test)
        self._match = None         # validator(window) -> True when it's our reply
        self._resp = None          # the extracted response frame, once seen
        self._install_hooks()
        # The factory boots only with a valid config flash (docs/21); provide one
        # unless the caller already attached an SPI device. Inert for our image.
        if getattr(sim, "spi_flash", None) is None:
            sim.attach_config_flash()
        # Use the exception engine, not plain SysTick injection: an interrupt-driven
        # dongle UART (RX and TX) needs the IRQ delivered (sim.pend_irq); the engine
        # also runs the factory's RTOS. A polled firmware is unaffected.
        sim.enable_rtos(systick)
        sim.run_reset(max_insn=boot_insn)   # boot through init into the loop

    # -- UART glue (added on top of arm_sim's own peripheral hooks) ----------
    def _install_hooks(self):
        uc = self.sim.uc
        for name, base, _vec in self._ports:
            sr, dr = base + 0x00, base + 0x04
            uc.hook_add(UC_HOOK_MEM_READ,  self._mk_sr_read(sr),      begin=sr, end=sr + 4)
            uc.hook_add(UC_HOOK_MEM_READ,  self._mk_dr_read(name, dr), begin=dr, end=dr + 4)
            uc.hook_add(UC_HOOK_MEM_WRITE, self._mk_dr_write(name),   begin=dr, end=dr + 4)

    def _mk_sr_read(self, sr):
        def on_sr_read(uc, access, addr, size, value, ud):
            # arm_sim already forced SR=TXE|TC here; add RXNE while a byte waits.
            if self._rx:
                cur = struct.unpack("<I", uc.mem_read(sr, 4))[0]
                uc.mem_write(sr, struct.pack("<I", cur | SR_RXNE))
            return True
        return on_sr_read

    def _mk_dr_read(self, name, dr):
        def on_dr_read(uc, access, addr, size, value, ud):
            if self._cur == name:
                self._saw_dr = True            # the firmware receives on this port
            if self._rx:
                uc.mem_write(dr, struct.pack("<I", self._rx.pop(0)))
                # Re-pend the IRQ while bytes remain so an interrupt-driven RX
                # delivers them back-to-back (idempotent; a polled RX ignores it).
                if self._rx and self._cur == name:
                    self._pend(name)
            return True
        return on_dr_read

    def _mk_dr_write(self, name):
        def on_dr_write(uc, access, addr, size, value, ud):
            buf = self._tx.setdefault(name, bytearray())
            buf.append(value & 0xFF)
            if self._cur == name:
                self._pend(name)   # TX ISR: re-pend so the reply drains back-to-back
                # Stop as soon as our reply appears as a contiguous tail window.
                if self._resp is None and self._rlen and len(buf) >= self._rlen:
                    window = bytes(buf[-self._rlen:])
                    if self._match(window):
                        self._resp = window
                        self.sim._halt = True
                        uc.emu_stop()
            return True
        return on_dr_write

    def _pend(self, name):
        """Deliver the IRQ of port `name` if the firmware has armed it there."""
        for n, base, vec in self._ports:
            if n == name and (self.sim.r32(base + 0x0C) & (CR1_RXNEIE | CR1_TXEIE)):
                self.sim.pend_irq(vec)
            if n == name:
                return

    # -- one request/response transaction ------------------------------------
    def _run_on_port(self, port, request, rlen, match, budget):
        name, base, vec = port
        cr1 = base + 0x0C
        self._cur = name
        self._rx = list(request)
        self._tx[name] = bytearray()
        self._rlen = rlen
        self._match = match
        self._resp = None
        self._saw_dr = False
        remaining = budget
        used = 0
        while self._resp is None and remaining > 0:
            c = self.sim.r32(cr1)
            if (c & CR1_RXNEIE and self._rx) or (c & CR1_TXEIE):
                self.sim.pend_irq(vec)
            self.sim.run(_TXN_CHUNK)        # resume; on_dr_write stops us on a reply
            remaining -= _TXN_CHUNK
            used += _TXN_CHUNK
            # Early bail: if the firmware has not even *read* this port's data
            # register within a grace window, it is not receiving here -- don't
            # burn the whole budget on a dead port (e.g. our inert USART3 probe).
            if not self._saw_dr and used >= _PROBE_GRACE:
                break
        self._cur = None
        return self._resp

    def _ensure_port(self):
        """Lazily latch the port the image answers on, using an **idempotent read
        probe** (never the caller's real request, which may be a write). A read of
        IR 0 (operating state) is served by both images and mutates nothing. Each
        port gets the full transaction budget, so the answering port replies (and
        is latched) before the next port is tried -- critical because we must not
        probe the factory's UART5 at all (see DEFAULT_PORTS). A probe returns as
        soon as a reply is seen, so the answering port is cheap; only a genuine
        miss burns the full budget (our firmware's inert USART3 probe)."""
        if self._port is not None:
            return
        probe = _frame(self.addr, FC_READ_INPUT, struct.pack("<HH", 0, 1), self.sn)
        rlen = _HDR + 3 + 2 + _CRC

        def match(w):
            return (w[0] == self.addr and w[1] == FC_READ_INPUT and _crc_ok(w)
                    and w[_HDR + 2] == 2)

        for port in self._ports:
            if self._run_on_port(port, probe, rlen, match, self._txn_insn) is not None:
                self._port = port
                return

    def _txn(self, request, rlen, match):
        self._ensure_port()
        port = self._port if self._port is not None else self._ports[-1]
        return self._run_on_port(port, request, rlen, match, self._txn_insn)

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
