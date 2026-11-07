#!/usr/bin/env python3
"""Inverter -> battery CAN keep-alive TX -- the SAME spec, factory-vs-ours (T11b).

The inverter transmits a keep-alive on CAN1 so the pack keeps its contactor closed
and keeps streaming telemetry. We capture what each image puts on the TX mailbox
(no symbols, black box over the bxCAN TX registers -- tests/arm_sim_can.py
capture_tx) and compare.

Oracle (factory ceaa-07xx, docs/39 T11b): the inverter sends **0x305, DLC 8,
payload all-zero**, periodically, only once it has received battery telemetry, and
the payload does **not** vary with battery state (nominal vs faulted/low both
all-zero). Our firmware (src/main.c, can_port.c) already sends exactly that, so the
two agree. Requires the factory's TX task to run -- i.e. the RTOS (T02).
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

INV_ALIVE = 0x305          # BMS_CAN_ID_INV_ALIVE (bms_can_map.h)
_KEYS = ("PA8", "PA11", "PC8", "PC9")


def _feed(battery):
    """A full, healthy telemetry set -- the factory only starts its TX once it has
    seen the pack."""
    battery.send_soc_soh(77, 96)
    battery.send_measurements(5325, 150, 231)
    battery.send_limits(560, 500, 500, 450)
    battery.send_alarms(0, 0, pack_count=1)


class _Backend:
    name = "?"

    def available(self):
        try:
            self._make()
            return True
        except Exception:
            return False

    def keepalives(self, max_insn=None, chunk=2_000_000):
        """Boot the image with a live pack on CAN1 and capture its keep-alive TX.
        Runs in chunks, re-feeding RX each chunk, and stops as soon as a 0x305
        frame has been transmitted."""
        sim, battery = self._make()
        done, limit = 0, max_insn or self.max_insn
        while done < limit:
            _feed(battery)
            sim.run(chunk)
            done += chunk
            if battery.tx_frames(INV_ALIVE):
                break
        return battery.tx_frames(INV_ALIVE)


class FactoryBackend(_Backend):
    name = "factory"
    max_insn = 24_000_000      # factory emits ~1 per ~20M insns

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
        sim.set_input("PD8", 1)                 # detect input high (docs/16)
        battery = CanBattery(sim, capture_tx=True)   # hooks before boot
        ModbusDsp(sim)                          # boots under enable_rtos()
        return sim, battery


class OursBackend(_Backend):
    name = "ours"
    max_insn = 40_000_000      # ours' keep-alive is ~1 Hz = 1000 ticks

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
        battery = CanBattery(sim, capture_tx=True)
        ModbusDongle(sim)
        return sim, battery
