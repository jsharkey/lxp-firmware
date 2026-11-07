#!/usr/bin/env python3
"""Whole-surface read sweep -- the SAME seeded state, factory-vs-ours (docs/39 T23).

Boots an image into a fixed, reproducible state (a battery CAN snapshot + default
RTC), snapshots it, then reads **every** register the dongle Modbus map defines
-- IR 0-159, IR 5000-5126, HR 0-255 -- in spec-legal chunks (<=40, no 40-group
crossing) and records value-or-exception per register. `restore()` per chunk
keeps each read hermetic (warm once, clone per case -- docs/19).

**Seed level = CAN + RTC, NOT the HR-settings table.** The factory's USART3
fallback slave (the port the harness reaches) goes **silent** once its settings
are written over the wire -- writing a mode/enable register (e.g. SysEnable /
SysType / FuncEn) takes it out of the state where it answers EG4-Modbus on USART3
(unlike the real UART5 dongle handler, a T02 task). So the HR surface here is the
**cold** state: ours boots blank (0), the factory boots with its provisioned
config defaults, and that gap is the dominant HR diff below (a power-on-defaults
gap -- ours has none; see T03/T12). Per-register settings PARITY is proven
elsewhere (write path T04, persistence T03); seeding every HR and re-sweeping both
is the T23b follow-up, blocked on keeping the factory USART3 slave alive under
settings writes.

It also captures the **framing** behaviour (a read crossing a 40-group boundary,
a read longer than 40, a zero-length read, an out-of-map address): our firmware
enforces the documented dongle rule (exception 2), while the factory's USART3
slave -- the port the harness reaches, not the real UART5 dongle handler (a T02
task) -- is lenient. That asymmetry is expected and recorded, not asserted equal.

The two backends read the same way; test_regsweep.py diffs them into the parity
scoreboard. ComAddr (HR 15) is deliberately NOT seeded: writing it moves the
slave's Modbus address (T12), which would silence the master mid-sweep; its
parity is covered by test_comaddr_changes_slave_address_live.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

from arm_sim_modbus import FC_READ_INPUT, FC_READ_HOLDING          # noqa: E402

_KEYS = ("PA8", "PA11", "PC8", "PC9")

# A fixed battery CAN snapshot so the BMS block (IR 81-106, IR 5) is populated
# identically on both images.
CAN_SNAP = dict(soc=77, soh=96, v_cv=5325, i_ca=150, t_dc=231,
                chg_v=560, fault=0x0102, warn=0x0408, modules=3)

# The whole readable surface, in spec-legal chunks (<=40, 40-group aligned).
CHUNKS = ([("IR", FC_READ_INPUT, s, min(40, 160 - s)) for s in range(0, 160, 40)]
          + [("IR", FC_READ_INPUT, s, min(40, 5127 - s)) for s in range(5000, 5127, 40)]
          + [("HR", FC_READ_HOLDING, s, min(40, 256 - s)) for s in range(0, 256, 40)])

# Framing probes: (label, func, reg, n, crosses-a-group?). Our firmware must
# reject all four; the factory USART3 slave is recorded as-is.
FRAMING = [
    ("cross-40-group", FC_READ_INPUT, 30, 20),   # 30..49 spans groups 0 and 1
    ("over-40",        FC_READ_INPUT, 0, 41),
    ("zero-length",    FC_READ_INPUT, 20, 0),
    ("out-of-map",     FC_READ_INPUT, 300, 1),
]


class _Backend:
    name = "?"

    def available(self):
        try:
            self._make()
            return True
        except Exception:
            return False

    def _seed(self, mb, battery):
        s = CAN_SNAP
        battery.send_soc_soh(s["soc"], s["soh"])
        battery.send_measurements(s["v_cv"], s["i_ca"], s["t_dc"])
        battery.send_limits(s["chg_v"])
        battery.send_alarms(s["fault"], s["warn"], pack_count=s["modules"])
        battery.settle()

    def sweep(self):
        """-> ({(space,num): ("ok",v)|("exc",code)|("silent",)}, {framing label: result})."""
        sim, battery, mb = self._make()
        self._seed(mb, battery)
        snap = sim.snapshot()
        surface = {}
        for space, func, start, n in CHUNKS:
            sim.restore(snap)
            r = mb.probe_read(func, start, n)
            for i in range(n):
                surface[(space, start + i)] = r if r[0] != "ok" else ("ok", r[1][i])
        framing = {}
        for label, func, reg, n in FRAMING:
            sim.restore(snap)
            framing[label] = mb.probe_read(func, reg, n)
        return surface, framing


class FactoryBackend(_Backend):
    name = "factory"

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(ROOT, "reference", "symbols.csv")

    def _make(self):
        from arm_sim import ArmSim, load_symbols_csv
        from arm_sim_can import CanBattery
        from arm_sim_modbus import ModbusDsp
        if not os.path.exists(self.image):
            raise FileNotFoundError(self.image)
        sim = ArmSim(self.image, load_symbols_csv(self.symbols))
        for k in _KEYS:
            sim.set_input(k, 1)
        battery = CanBattery(sim)
        mb = ModbusDsp(sim)
        return sim, battery, mb


class OursBackend(_Backend):
    name = "ours"

    def __init__(self, bin_path, elf_path):
        self.bin_path = bin_path
        self.elf_path = elf_path

    def _make(self):
        from arm_sim import ArmSim, load_symbols_nm
        from arm_sim_can import CanBattery
        from arm_sim_modbus import ModbusDongle
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        sim = ArmSim(self.bin_path, load_symbols_nm(self.elf_path))
        for k in _KEYS:
            sim.set_input(k, 1)
        battery = CanBattery(sim)
        mb = ModbusDongle(sim)
        return sim, battery, mb
