#!/usr/bin/env python3
"""Shared HR write-validation contract -- the SAME spec, factory-vs-ours.

The dongle slave range-checks a holding-register write. We drive each image's
real write path over the Modbus dongle and classify its reply: a normal echo
(accepted) or a Modbus exception (rejected, with code). Both images must give the
same verdict for each vector (parity by contract; docs/39 T04).

Factory verdicts recovered by fresh-boot-per-value probing (the harness RX state
degrades across a rejected write, so every probe boots fresh):
  in-range            -> accept (echo)
  out-of-range        -> reject, exception 3 (ILLEGAL_VALUE), value not stored
  read-only register  -> reject, exception 4 (SLAVE_FAILURE)
A few registers enforce only one bound (HR 101/105 upper) -- see docs/31; our
settings_validate() replicates that for parity.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

# (label, reg, value, expected_verdict). Verdicts: "accept", "reject:3", "reject:4".
WRITE_VECTORS = [
    ("HR20 PVInputModel in-range",  20,     3, "accept"),
    ("HR20 PVInputModel >max",      20,     8, "reject:3"),
    ("HR66 ACChgPower in-range",    66,    50, "accept"),
    ("HR66 ACChgPower >max",        66,   101, "reject:3"),
    ("HR15 ComAddr in-range",       15,    10, "accept"),
    ("HR15 ComAddr >max",           15,   151, "reject:3"),
    ("HR105 EOD in-range",         105,    50, "accept"),
    ("HR105 EOD <min",             105,     9, "reject:3"),
    ("HR105 EOD >spec-max (quirk)",105,    91, "accept"),     # docs/31: upper not enforced
    ("HR101 ChargeCurr >spec-max (quirk)", 101, 141, "accept"),  # docs/31: upper not enforced
    ("HR9 FW-version read-only",     9, 0x1234, "reject:4"),
]


def _crc16(buf):
    crc = 0xFFFF
    for b in buf:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def _verdict_from_tx(tx, addr, func):
    """Scan a captured TX byte stream for a valid echo (func) or exception
    (func|0x80) frame addressed to `addr`. Return 'accept', 'reject:<code>', or
    'silent'. The EG4 frame is addr, func[, SN...], body..., CRC-16/LE."""
    i = 0
    n = len(tx)
    while i < n - 4:
        if tx[i] == addr and tx[i + 1] in (func, func | 0x80):
            is_exc = tx[i + 1] == (func | 0x80)
            for ln in range(5, 20):
                if i + ln <= n:
                    fr = bytes(tx[i:i + ln])
                    if _crc16(fr[:-2]) == (fr[-2] | (fr[-1] << 8)):
                        return ("reject:%d" % fr[-3]) if is_exc else "accept"
        i += 1
    return "silent"


class _Backend:
    """Drive a holding-register write over the dongle on a FRESH boot and classify
    the reply. Subclasses provide _sim() -> a booted ArmSim with a ModbusDongle."""
    name = "?"
    FUNC_WRITE_SINGLE = 0x06

    def available(self):
        try:
            self._make()
            return True
        except Exception:
            return False

    def write_verdict(self, reg, val):
        sim, mb = self._make()
        from arm_sim_modbus import _frame, FC_WRITE_SINGLE
        # Latch whichever UART this image answers the dongle on (factory: USART3;
        # ours: UART5 -- the dongle auto-detects, T01). The dongle captures the TX
        # of each port into mb._tx[name]; we drive the write and scan that buffer
        # for an echo or exception frame, stopping as soon as one appears.
        mb._ensure_port()
        name, base, _vec = mb._port
        req = _frame(mb.addr, FC_WRITE_SINGLE, struct.pack("<HH", reg, val), mb.sn)
        mb._tx[name] = bytearray()
        mb._rx = list(req)
        mb._cur = name
        mb._rlen = 0
        mb._match = lambda w: False      # don't let the dongle stop us; we scan the TX
        mb._resp = None
        remaining = 6_000_000
        while remaining > 0:
            mb._pend(name)               # deliver the port IRQ if the firmware armed it
            sim.run(40_000)
            remaining -= 40_000
            if _verdict_from_tx(mb._tx.get(name, b""), mb.addr, self.FUNC_WRITE_SINGLE) != "silent":
                break
        return _verdict_from_tx(mb._tx.get(name, b""), mb.addr, self.FUNC_WRITE_SINGLE)


class FactoryBackend(_Backend):
    name = "factory"

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(
            os.path.dirname(__file__), "..", "reference", "symbols.csv")

    def _make(self):
        from arm_sim import ArmSim, load_symbols_csv
        from arm_sim_modbus import ModbusDongle
        if not os.path.exists(self.image):
            raise FileNotFoundError(self.image)
        sim = ArmSim(self.image, load_symbols_csv(self.symbols))
        mb = ModbusDongle(sim, boot_insn=1_000_000)
        return sim, mb


class OursBackend(_Backend):
    name = "ours"

    def __init__(self, bin_path, elf_path):
        self.bin_path = bin_path
        self.elf_path = elf_path

    def _make(self):
        from arm_sim import ArmSim, load_symbols_nm
        from arm_sim_modbus import ModbusDongle
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        sim = ArmSim(self.bin_path, load_symbols_nm(self.elf_path))
        mb = ModbusDongle(sim, boot_insn=4_000_000)
        return sim, mb
