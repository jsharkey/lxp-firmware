#!/usr/bin/env python3
"""Shared accumulated-energy contract -- the SAME spec, factory-vs-ours.

The ARM maintains the energy input registers itself (IR 28-37 daily, IR 40-59
cumulative, 0.1 kWh) by integrating instantaneous power telemetry over time. The
factory accumulator (07-series fn 0x0801fbc4, served by the input getter
0x0803289c; struct 0x20009954) does, per tick and GATED on a running state:

    sub[ch] += power[ch] >> 1
    if sub[ch] >= 3_600_001:  day[ch] += 1;  all[ch] += 1;  sub[ch] -= 3_600_000

Both images are driven identically: seed a channel's power + the operating state,
run N accumulation ticks, and read Epv1_day (IR 28) / Epv1_all (IR 40/41). Our
firmware must reproduce the factory's exact arithmetic -- so the two agree on
every vector (parity by contract; cf. timewindow/dsppush/safety contracts). docs/37.

Epv1 is channel 0 (power source PV1). Values are chosen so the counts are exact:
 * power/2 == threshold (7_200_002)  -> one 0.1 kWh count per tick
 * power/2 == threshold/2 (3_600_002)-> one count per two ticks
 * state < 3                          -> gated off, nothing accumulates
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

# (power, nticks, state, expected Epv1_day, expected Epv1_all)
ENERGY_VECTORS = [
    ("1 count/tick",          7_200_002, 5, 0x40, 5, 5),
    ("1 count / 2 ticks",     3_600_002, 4, 0x40, 2, 2),
    ("gated off (state<3)",   7_200_002, 5, 0x02, 0, 0),
    ("no power",                      0, 6, 0x40, 0, 0),
    ("no ticks",              7_200_002, 0, 0x40, 0, 0),
    ("running state 0x10",    7_200_002, 3, 0x10, 3, 3),
]


class FactoryBackend:
    """Factory image: drive the real Epv1 accumulator 0x0801fbc4, read via the
    input getter 0x0803289c. Each probe runs on a fresh emulator (clean RAM)."""
    name = "factory"
    ACCUM  = 0x0801fbc4
    GETTER = 0x0803289c
    STRUCT = 0x20009954
    BANK_STATE = 0x20009e55   # safety-CPU bank [+1]: operating state (>=3 => running)
    PV1_PWR    = 0x2000a100   # STATUS 0x2000a0d8 + 0x28: PV1 instantaneous power
    STATUS     = 0x2000a0d8

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(
            os.path.dirname(__file__), "..", "reference", "symbols.csv")

    def available(self):
        if not os.path.exists(self.image):
            return False
        try:
            from emu import Emu  # noqa: F401
            return True
        except Exception:
            return False

    def accumulate(self, power, nticks, state):
        from emu import Emu
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(self.BANK_STATE - 1, bytes([0, state & 0xFF]))  # bank[0]=0, bank[+1]=state
        e.wbytes(self.STRUCT, bytes([0] * 0xD0))
        e.wbytes(self.STATUS, bytes([0] * 0x80))
        e.uc.mem_write(self.PV1_PWR, struct.pack("<I", power & 0xFFFFFFFF))
        for _ in range(nticks):
            e.call(self.ACCUM)
        day = e.call(self.GETTER, (28,)) & 0xFFFF
        allv = (e.call(self.GETTER, (40,)) & 0xFFFF) | ((e.call(self.GETTER, (41,)) & 0xFFFF) << 16)
        return day, allv


class OursBackend:
    """Our firmware: drive energy_set_power()/energy_tick() by symbol, publish to
    a scratch input-register image, and read IR 28 / 40-41 back from it."""
    name = "ours"
    SCRATCH = 0x30000000      # scratch IR image (>=60 u16); mapped in _sim()

    def __init__(self, bin_path, elf_path):
        self.bin_path = bin_path
        self.elf_path = elf_path

    def _sim(self):
        from arm_sim import ArmSim, load_symbols_nm
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        sim = ArmSim(self.bin_path, load_symbols_nm(self.elf_path))
        sim.uc.mem_map(self.SCRATCH, 0x1000)
        return sim

    def available(self):
        try:
            self._sim()
            return True
        except Exception:
            return False

    def accumulate(self, power, nticks, state):
        sim = self._sim()
        # fresh RAM => g_energy is zero. Seed channel 0 (PV1) power, run ticks.
        sim.call("energy_set_power", (0, power & 0xFFFFFFFF))
        for _ in range(nticks):
            sim.call("energy_tick", (state & 0xFF,))
        sim.wbytes(self.SCRATCH, bytes([0] * 0x80))
        sim.call("energy_publish", (self.SCRATCH,))
        day = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 28, 2))[0]
        lo = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 40, 2))[0]
        hi = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 41, 2))[0]
        return day, lo | (hi << 16)

    # --- daily rollover (extra credit) --------------------------------------
    def rollover(self, power, nticks, state, day1, day2):
        """Accumulate, latch day1, then cross to day2; return (day,all) after."""
        sim = self._sim()
        sim.call("energy_set_power", (0, power & 0xFFFFFFFF))
        for _ in range(nticks):
            sim.call("energy_tick", (state & 0xFF,))
        sim.call("energy_rollover", (day1 & 0xFF,))   # first obs: latch, no reset
        sim.call("energy_rollover", (day2 & 0xFF,))   # day change -> daily resets
        sim.wbytes(self.SCRATCH, bytes([0] * 0x80))
        sim.call("energy_publish", (self.SCRATCH,))
        day = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 28, 2))[0]
        lo = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 40, 2))[0]
        hi = struct.unpack("<H", sim.rbytes(self.SCRATCH + 2 * 41, 2))[0]
        return day, lo | (hi << 16)
