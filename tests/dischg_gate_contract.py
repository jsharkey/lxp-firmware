#!/usr/bin/env python3
"""Shared discharge-by-voltage hysteresis-gate contract (docs/41, T15).

The factory decides "is battery discharge allowed now?" with a latched voltage
hysteresis (DischgCtrlType = by voltage): turn ON once V reaches `start`, stay on
until V falls below `stop`. Reverse-engineered as `sub_0801ed28`'s voltage path on
`com_flat.bin`:

    v = (uint16 safety-bank battery voltage @+0x0a) / 10      # signed divide
    active = active ? (v >= stop) : (v >= start)              # verdict byte 0x2000aa5f

This module drives that real evaluator in isolation as the oracle: seed the
discharge master-enable (settings+0x23 bit 13), the mode = by-voltage
(settings+0x33 bits 4-5 = 0), the thresholds (settings+0x46 start / +0x48 stop),
the bank voltage (+0x0a) and the previous verdict, call it, and read the verdict
byte. Our firmware's pure reimplementation `inv_dischg_volt_gate()` is checked
against the SAME vectors by the toolchain-free host test tests/test_dischg_gate.c.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# ceaa05 / com_flat.bin addresses (T15, docs/41).
SETTINGS = 0x20009854
BANK     = 0x20009e54        # safety telemetry bank on this image
EVAL     = 0x0801ed28        # the schedule-gate evaluator
VERDICT  = 0x2000aa5f        # discharge-by-voltage "active now" byte
OFF_EN   = 0x23              # settings offset: master-enable word (bit 13)
OFF_MODE = 0x33              # settings offset: HR 120 mode word (bits 4-5 DischgCtrlType)
OFF_START = 0x46             # settings offset: turn-ON threshold
OFF_STOP  = 0x48             # settings offset: turn-OFF threshold
OFF_VBAT  = 0x0a             # bank offset: inverter battery voltage (0.1 V)

START, STOP = 480, 460       # deadband used by the vectors

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
        """Drive sub_0801ed28's voltage path once; return its latched verdict byte."""
        import sys
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from emu import Emu
        e = Emu(self.image, self.symbols)
        # discharge master-enable: settings+0x23 bit 13
        w = struct.unpack("<I", e.rbytes(SETTINGS + OFF_EN, 4))[0] | (1 << 13)
        e.uc.mem_write(SETTINGS + OFF_EN, struct.pack("<I", w))
        # mode = by voltage: settings+0x33 bits 4-5 = 0
        hv = struct.unpack("<H", e.rbytes(SETTINGS + OFF_MODE, 2))[0] & ~(3 << 4)
        e.uc.mem_write(SETTINGS + OFF_MODE, struct.pack("<H", hv))
        # thresholds + bank voltage (bank word = divided value * 10) + prior verdict
        e.uc.mem_write(SETTINGS + OFF_START, struct.pack("<H", start & 0xFFFF))
        e.uc.mem_write(SETTINGS + OFF_STOP, struct.pack("<H", stop & 0xFFFF))
        e.uc.mem_write(BANK + OFF_VBAT, struct.pack("<H", (vbat_divided * 10) & 0xFFFF))
        e.uc.mem_write(VERDICT, bytes([1 if prev else 0]))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(EVAL)
        return e.rbytes(VERDICT, 1)[0] != 0
