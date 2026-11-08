#!/usr/bin/env python3
"""Shared generator-charge-by-voltage hysteresis-gate contract (T16, HR194_198 doc).

The factory decides whether to charge from the generator with a latched voltage
hysteresis in the CHARGE direction (start when the battery is low, stop when high).
Reverse-engineered on the canonical 07 image (`ceaa-07xx_vE_260214.bin`) as the
voltage path of the generator-charge evaluator `sub_08035050` -- the self-contained
block `0x08035086 … 0x080350dc`, verdict byte `0x2000dbc0`:

    v = (uint16 safety-bank battery voltage @+0x0a) / 10     # signed divide
    if not active: active = v <  start_v                     # start when low (HR194 / +0xac)
    else:          active = not (v >= end_v and stop_ok)     # stop when high (HR195 / +0xae) AND confirmed

The **stop** also requires two DSP/safety-bank status bits -- `bank+0xb6` bit 11 AND
`bank+0xbc` bit 15 (`stop_ok`). The block needs only the settings base in r1, so the
oracle drives it directly (the enclosing evaluator's GenChargeType/health/mode
preconditions are separate). Our firmware's pure `inv_gen_charge_volt_gate()` is
held to the SAME vectors by the host test tests/test_gen_charge.c.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Canonical 07 image addresses (T16).
SETTINGS   = 0x2000c85c
BANK       = 0x2000ce5c
BLOCK      = 0x08035086        # generator-charge-by-voltage block entry
STOP_AFTER = 0x080350dc        # block exit (verdict written by here)
VERDICT    = 0x2000dbc0        # generator-charge "active now" byte
OFF_START  = 0xac             # settings: HR 194 GenChgStartVolt
OFF_END    = 0xae             # settings: HR 195 GenChgEndVolt
OFF_VBAT   = 0x0a             # bank: battery voltage (0.1 V)

START, END = 464, 480        # HR194 46.4 V, HR195 48.0 V (defaults-ish)

# (label, prev_active, vbat_divided, stop_ok, expected_active). Charge direction:
# on at v<START from off, off at v>=END from on BUT only when stop_ok.
VECTORS = [
    ("off 450 < start -> on",   False, 450, True,  True),
    ("off 463 < start -> on",   False, 463, True,  True),
    ("off 464 == start stays",  False, 464, True,  False),
    ("off 490 > start off",     False, 490, True,  False),
    ("off 470 in band",         False, 470, True,  False),
    ("on 450 stays",            True,  450, True,  True),
    ("on 479 < end stays",      True,  479, True,  True),
    ("on 480 == end +ok -> off", True,  480, True,  False),
    ("on 490 +ok -> off",       True,  490, True,  False),
    ("on 470 in band stays",    True,  470, True,  True),
    ("on 490 no-confirm stays", True,  490, False, True),
    ("on 480 no-confirm stays", True,  480, False, True),
]


def predict(prev, vbat, stop_ok):
    """The pure hysteresis spec both sides must satisfy."""
    if not prev:
        return vbat < START
    return not (vbat >= END and stop_ok)


# --- SOC sibling (GenChargeType = 1) --------------------------------------------
# Same charge-direction hysteresis on the battery SOC byte: start when SOC is low,
# stop when SOC is high AND stop_ok. Factory block 0x08035198 … 0x080351de, verdict
# byte 0x2000dbc1; SOC byte at relayed struct 0x2000d7b0; thresholds are 1-byte,
# HR196 GenChgStartSOC @ settings+0xb0, HR197 GenChgEndSOC @ settings+0xb1.
SOC_BASE   = 0x2000d7b0        # relayed battery-SOC struct (byte 0 = SOC %)
SOC_BLOCK  = 0x08035198        # gen-charge-by-SOC block entry
SOC_STOP   = 0x080351de        # block exit (verdict written by here)
SOC_VERD   = 0x2000dbc1        # generator-charge-by-SOC "active now" byte
OFF_SSTART = 0xb0             # settings: HR 196 GenChgStartSOC (byte)
OFF_SEND   = 0xb1             # settings: HR 197 GenChgEndSOC   (byte)

SSTART, SEND = 20, 100       # HR196 20 %, HR197 100 % (manual defaults)

# (label, prev_active, soc, stop_ok, expected_active).
SOC_VECTORS = [
    ("off 10 < start -> on",     False, 10,  True,  True),
    ("off 19 < start -> on",     False, 19,  True,  True),
    ("off 20 == start stays",    False, 20,  True,  False),
    ("off 50 > start off",       False, 50,  True,  False),
    ("on 10 stays",              True,  10,  True,  True),
    ("on 99 < end stays",        True,  99,  True,  True),
    ("on 100 == end +ok -> off", True,  100, True,  False),
    ("on 50 in band stays",      True,  50,  True,  True),
    ("on 100 no-confirm stays",  True,  100, False, True),
]


def predict_soc(prev, soc, stop_ok):
    """The pure SOC-hysteresis spec both sides must satisfy."""
    if not prev:
        return soc < SSTART
    return not (soc >= SEND and stop_ok)


# --- shadow gates (secondary request -> da3a bit13) -----------------------------
# A second, more-eager pair the factory evaluates right after each primary gate:
# voltage block 0x080350dc..0x08035134 (verdict 0x2000dbbe), SOC block
# 0x080351de..0x08035220 (verdict 0x2000dbbf). Wider start band gated by `wide`
# (safety bank +0xbc bit31) and a plain (unconfirmed) stop.
SHV_BLOCK, SHV_STOP, SHV_VERD = 0x080350dc, 0x08035146, 0x2000dbbe
SHS_BLOCK, SHS_STOP, SHS_VERD = 0x080351de, 0x08035232, 0x2000dbbf
OFF_WIDE = 0xbc              # safety bank: +0xbc bit31 = DSP "allow wider band"

# Shadow thresholds are chosen with end > start + 30 so the `wide` band is active
# (the extra start region start <= v < end-30 actually exists; with the default
# 464/480 gen thresholds the +30 band collapses inside the normal start and `wide`
# is inert -- which is itself a verified property, see test_factory_shadow_wide_inert).
SHV_START, SHV_END = 464, 510     # 46.4 V .. 51.0 V: wide band 464 <= v < 480

# (label, prev, vbat_divided, wide, expected)
SHADOW_V_VECTORS = [
    ("off 450<start on",        False, 450, False, True),
    ("off 470 band no-wide off",False, 470, False, False),
    ("off 470 band wide on",    False, 470, True,  True),   # 470+30=500 < 510 -> eager on
    ("off 479 wide on",         False, 479, True,  True),   # 479+30=509 < 510 -> on
    ("off 480 wide edge off",   False, 480, True,  False),  # 480+30=510 !< 510; 480>=464 -> off
    ("on 490 stays",            True,  490, False, True),
    ("on 509 < end stays",      True,  509, False, True),
    ("on 510 == end -> off",    True,  510, False, False),  # plain stop, no confirm
    ("on 520 -> off",           True,  520, True,  False),
]
# (label, prev, soc, wide, expected). start=20/end=100: wide band 20 <= soc < 98.
SHADOW_S_VECTORS = [
    ("off 10<start on",        False, 10,  False, True),
    ("off 50 band no-wide off",False, 50,  False, False),
    ("off 50 band wide on",    False, 50,  True,  True),   # 50+2=52 < 100 -> eager on
    ("off 97 wide on",         False, 97,  True,  True),
    ("off 98 wide edge off",   False, 98,  True,  False),  # 98+2=100 !< 100; 98>=20 -> off
    ("on 50 stays",            True,  50,  False, True),
    ("on 99 < end stays",      True,  99,  False, True),
    ("on 100 == end -> off",   True,  100, False, False),
]


def predict_shadow_v(prev, v, wide, start=SHV_START, end=SHV_END):
    if not prev:
        return (v < start) or (wide and v + 30 < end)
    return not (v >= end)


def predict_shadow_s(prev, soc, wide, start=SSTART, end=SEND):
    if not prev:
        return (soc < start) or (wide and soc + 2 < end)
    return not (soc >= end)


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

    def verdict(self, prev, vbat_divided, stop_ok, start=START, end=END):
        """Drive the gen-charge-by-voltage block once; return its latched verdict."""
        from emu import Emu
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(SETTINGS + OFF_START, struct.pack("<H", start & 0xFFFF))
        e.uc.mem_write(SETTINGS + OFF_END, struct.pack("<H", end & 0xFFFF))
        e.uc.mem_write(BANK + OFF_VBAT, struct.pack("<H", (vbat_divided * 10) & 0xFFFF))
        if stop_ok:                                       # the two DSP stop-confirm bits
            e.uc.mem_write(BANK + 0xb6, struct.pack("<H", 1 << 11))
            e.uc.mem_write(BANK + 0xbc, struct.pack("<I", 1 << 15))
        e.uc.mem_write(VERDICT, bytes([1 if prev else 0]))
        e.stop_at.add(STOP_AFTER)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(BLOCK, args=(0, SETTINGS))             # r1 = settings base
        return e.rbytes(VERDICT, 1)[0] != 0

    def verdict_soc(self, prev, soc, stop_ok, start=SSTART, end=SEND):
        """Drive the gen-charge-by-SOC block once; return its latched verdict."""
        from emu import Emu
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(SETTINGS + OFF_SSTART, bytes([start & 0xFF]))
        e.uc.mem_write(SETTINGS + OFF_SEND, bytes([end & 0xFF]))
        e.uc.mem_write(SOC_BASE, bytes([soc & 0xFF]))
        if stop_ok:                                       # same two DSP stop-confirm bits
            e.uc.mem_write(BANK + 0xb6, struct.pack("<H", 1 << 11))
            e.uc.mem_write(BANK + 0xbc, struct.pack("<I", 1 << 15))
        e.uc.mem_write(SOC_VERD, bytes([1 if prev else 0]))
        e.stop_at.add(SOC_STOP)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(SOC_BLOCK, args=(0, SETTINGS, SOC_BASE))  # r1 = settings, r2 = SOC base
        return e.rbytes(SOC_VERD, 1)[0] != 0

    def verdict_shadow_v(self, prev, vbat_divided, wide, start=SHV_START, end=SHV_END):
        """Drive the shadow (secondary) voltage block; return its latched verdict."""
        from emu import Emu
        import contextlib
        import io
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(SETTINGS + OFF_START, struct.pack("<H", start & 0xFFFF))
        e.uc.mem_write(SETTINGS + OFF_END, struct.pack("<H", end & 0xFFFF))
        e.uc.mem_write(BANK + OFF_VBAT, struct.pack("<H", (vbat_divided * 10) & 0xFFFF))
        e.uc.mem_write(BANK + OFF_WIDE, struct.pack("<I", (1 << 31) if wide else 0))
        e.uc.mem_write(SHV_VERD, bytes([1 if prev else 0]))
        e.stop_at.add(SHV_STOP)
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(SHV_BLOCK, args=(0, SETTINGS))
        return e.rbytes(SHV_VERD, 1)[0] != 0

    def verdict_shadow_s(self, prev, soc, wide, start=SSTART, end=SEND):
        """Drive the shadow (secondary) SOC block; return its latched verdict."""
        from emu import Emu
        import contextlib
        import io
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(SETTINGS + OFF_SSTART, bytes([start & 0xFF]))
        e.uc.mem_write(SETTINGS + OFF_SEND, bytes([end & 0xFF]))
        e.uc.mem_write(SOC_BASE, bytes([soc & 0xFF]))
        e.uc.mem_write(BANK + OFF_WIDE, struct.pack("<I", (1 << 31) if wide else 0))
        e.uc.mem_write(SHS_VERD, bytes([1 if prev else 0]))
        e.stop_at.add(SHS_STOP)
        with contextlib.redirect_stdout(io.StringIO()):
            e.call(SHS_BLOCK, args=(0, SETTINGS, SOC_BASE))
        return e.rbytes(SHS_VERD, 1)[0] != 0
