#!/usr/bin/env python3
"""Shared discharge-by-voltage hysteresis-gate contract (docs/41, T15).

The factory decides "is battery discharge allowed now?" with a latched voltage
hysteresis (DischgCtrlType = by voltage): turn ON once V reaches `start`, stay on
until V falls below `stop`. Reverse-engineered on the **canonical 07 image**
(`reference/ceaa-07xx_vE_260214.bin`, md5 fc5b44bd…; see reference/README.md) as
the voltage path of the discharge-gate evaluator:

    v = (uint16 safety-bank battery voltage @+0x0a) / 10      # signed divide
    active = active ? (v >= stop) : (v >= start)              # verdict byte 0x2000dbc3

That path is a **self-contained block** (`0x080355c2 … 0x08035608`): given the
settings base in r1 it reads the previous verdict, the bank voltage and the two
thresholds and writes the new verdict. We drive exactly that block as the oracle
(the surrounding evaluator's health/mode preconditions are a separate concern —
the block is the gate *decision*). Our firmware's pure reimplementation
`inv_dischg_volt_gate()` is checked against the SAME vectors by the toolchain-free
host test tests/test_dischg_gate.c.

(The same logic lives in the 05-series image at `sub_0801ed28` / verdict
`0x2000aa5f` / settings `0x20009854` / bank `0x20009e54`; this contract targets the
committed 07 image per reference/README.md's "never write com_flat.bin" rule.)
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Canonical 07 image addresses (reference/README.md; verified T15).
SETTINGS   = 0x2000c85c        # settings / slot-config buffer base
BANK       = 0x2000ce5c        # safety telemetry bank
BLOCK      = 0x080355c2        # discharge-by-voltage hysteresis block entry
STOP_AFTER = 0x08035608        # block exit (verdict written by here)
VERDICT    = 0x2000dbc3        # discharge-by-voltage "active now" byte
OFF_START  = 0x46             # settings offset: turn-ON threshold
OFF_STOP   = 0x48             # settings offset: turn-OFF threshold
OFF_VBAT   = 0x0a             # bank offset: inverter battery voltage (0.1 V)

START, STOP = 480, 460       # deadband used by the vectors

# --- discharge-by-SOC sibling gate (DischgCtrlType = 1, verdict 0x2000dbc4) -------
# The SAME latched hysteresis on the battery SOC byte: 07 block 0x08035616..0x08035662
# reads the SOC byte (relayed struct 0x2000d7b0+0), its +0x13 precondition flag, and
# two 1-byte thresholds settings+0x4a (start) / +0x4b (stop), compared UNSIGNED.
SOC_BLOCK      = 0x08035616   # SOC-gate block entry (after the DischgCtrlType==1 test)
SOC_STOP_AFTER = 0x08035662   # block exit (verdict written by here)
SOC_VERDICT    = 0x2000dbc4   # discharge-by-SOC "active now" byte
SOC_SRC        = 0x2000d7b0   # relayed struct: SOC at +0, precondition flag at +0x13
OFF_SSTART     = 0x4a         # settings offset: SOC turn-ON threshold
OFF_SSTOP      = 0x4b         # settings offset: SOC turn-OFF threshold

SSTART, SSTOP = 50, 40       # SOC deadband used by the vectors

SOC_VECTORS = [
    ("off 39 < start",        False, 39, False),
    ("off 49 < start",        False, 49, False),
    ("off 50 == start -> on", False, 50, True),
    ("off 60 > start -> on",  False, 60, True),
    ("off 45 in band",        False, 45, False),
    ("on 60 stays",           True,  60, True),
    ("on 50 stays",           True,  50, True),
    ("on 40 == stop stays",   True,  40, True),
    ("on 39 < stop -> off",   True,  39, False),
    ("on 30 < stop -> off",   True,  30, False),
    ("on 45 in band stays",   True,  45, True),
]


def soc_predict(prev, soc):
    """The pure SOC hysteresis spec both sides must satisfy."""
    return (soc >= SSTOP) if prev else (soc >= SSTART)

# (label, prev_active, vbat_divided, expected_active). vbat is in the DIVIDED units
# the gate compares (the bank word fed is vbat*10). Hysteresis: on at >=START from
# off, off at <STOP from on, latched in the 460..480 band.
VECTORS = [
    ("off 450 < start",        False, 450, False),
    ("off 479 < start",        False, 479, False),
    ("off 480 == start -> on", False, 480, True),
    ("off 500 > start -> on",  False, 500, True),
    ("off 460 in band",        False, 460, False),
    ("off 470 in band",        False, 470, False),
    ("on 500 stays",           True,  500, True),
    ("on 480 stays",           True,  480, True),
    ("on 460 == stop stays",   True,  460, True),
    ("on 459 < stop -> off",   True,  459, False),
    ("on 450 < stop -> off",   True,  450, False),
    ("on 470 in band stays",   True,  470, True),
]


def predict(prev, vbat):
    """The pure hysteresis spec both sides must satisfy."""
    return (vbat >= STOP) if prev else (vbat >= START)


class Skip(Exception):
    pass


class FactoryBackend:
    name = "factory"

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(ROOT, "reference", "symbols.csv")

    def available(self):
        try:
            from emu import Emu  # noqa: F401
        except Exception:
            return False
        return os.path.exists(self.image)

    def verdict(self, prev, vbat_divided, start=START, stop=STOP):
        """Drive the discharge-by-voltage block once; return its latched verdict."""
        from emu import Emu
        e = Emu(self.image, self.symbols)
        # thresholds + bank voltage (bank word = divided value * 10) + prior verdict
        e.uc.mem_write(SETTINGS + OFF_START, struct.pack("<H", start & 0xFFFF))
        e.uc.mem_write(SETTINGS + OFF_STOP, struct.pack("<H", stop & 0xFFFF))
        e.uc.mem_write(BANK + OFF_VBAT, struct.pack("<H", (vbat_divided * 10) & 0xFFFF))
        e.uc.mem_write(VERDICT, bytes([1 if prev else 0]))
        e.stop_at.add(STOP_AFTER)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(BLOCK, args=(0, SETTINGS))      # r1 = settings base
        return e.rbytes(VERDICT, 1)[0] != 0

    def soc_verdict(self, prev, soc, start=SSTART, stop=SSTOP):
        """Drive the discharge-by-SOC sibling block once; return its latched verdict."""
        from emu import Emu
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(SETTINGS + OFF_SSTART, bytes([start & 0xFF]))
        e.uc.mem_write(SETTINGS + OFF_SSTOP, bytes([stop & 0xFF]))
        e.uc.mem_write(SOC_SRC, bytes([soc & 0xFF]))        # battery SOC byte
        e.uc.mem_write(SOC_SRC + 0x13, bytes([1]))          # precondition flag set
        e.uc.mem_write(SOC_VERDICT, bytes([1 if prev else 0]))
        e.stop_at.add(SOC_STOP_AFTER)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(SOC_BLOCK, args=(0, SETTINGS))  # r1 = settings base
        return e.rbytes(SOC_VERDICT, 1)[0] != 0
