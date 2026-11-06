#!/usr/bin/env python3
"""Shared ARM-computed-telemetry serve contract -- the SAME spec, factory-vs-ours.

A set of dongle input registers are computed by the ARM and served with a fixed
scaling (docs/39 T07, docs/22): the powers are kept internally in 0.1 W and served
IR = internal/10 (unsigned, truncating -- NOT a float; this corrects the roadmap's
guess), apparent power (Seps, IR 25) is served 1:1 in VA, and RunningTime (IR 69/70)
is a u32 seconds counter split low/high.

Both images are driven by injecting the ARM's INTERNAL quantities and reading the
served registers (the upstream V*I compute is DSP/safety-fed and injected here --
T05/T09):
  * factory: write the value into its STATUS-struct source, read via the input
    getter sub_0803289c.
  * ours:    pack an inv_telemetry_t, call inv_telemetry_publish(), read it back.
Both must produce SERVE_EXPECTED. IR 9 (Ppv3) is 2-MPPT-gated off on the factory
image, so it is covered on ours only.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

GETTER = 0x0803289c

# internal snapshot (0.1 W powers; VA for Seps; seconds for runtime)
SNAP = dict(p_pv1=32000, p_pv2=31805, p_pv3=15000, p_charge=15000, p_discharge=0,
            p_inv=48000, p_rec=99, p_eps=12000, s_eps=1300,
            p_togrid=20000, p_touser=655350, runtime_s=90061)

def _p(v):  # power serve: /10, u16-truncated
    return (v // 10) & 0xFFFF

# register -> expected served value (the contract). IR 69/70 are the runtime split.
SERVE_EXPECTED = {
    7:  _p(SNAP["p_pv1"]), 8: _p(SNAP["p_pv2"]),
    10: _p(SNAP["p_charge"]), 11: _p(SNAP["p_discharge"]),
    16: _p(SNAP["p_inv"]), 17: _p(SNAP["p_rec"]), 24: _p(SNAP["p_eps"]),
    25: SNAP["s_eps"] & 0xFFFF,                       # Seps 1:1
    26: _p(SNAP["p_togrid"]), 27: _p(SNAP["p_touser"]),
    69: SNAP["runtime_s"] & 0xFFFF, 70: (SNAP["runtime_s"] >> 16) & 0xFFFF,
}
OURS_EXTRA = {9: _p(SNAP["p_pv3"])}    # Ppv3 active only on a 3-MPPT build

# factory STATUS-struct source address per register (recovered by read-trace)
FACTORY_SRC = {7: 0x2000a100, 8: 0x2000a104, 10: 0x2000a0fc, 11: 0x2000a0f8,
               16: 0x2000a108, 17: 0x2000a114, 24: 0x2000a138, 26: 0x2000a110,
               27: 0x2000a10c}
FACTORY_SEPS = 0x2000a154            # IR 25 (u16 source)
FACTORY_RUNTIME = 0x2000995a         # IR 69/70 (u32 source)


class FactoryBackend:
    name = "factory"

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(
            os.path.dirname(__file__), "..", "reference", "symbols.csv")

    def available(self):
        try:
            from emu import Emu  # noqa: F401
            return os.path.exists(self.image)
        except Exception:
            return False

    def serve(self):
        from emu import Emu
        e = Emu(self.image, self.symbols)
        # inject the internal snapshot into the STATUS struct + runtime
        pw = {7: "p_pv1", 8: "p_pv2", 10: "p_charge", 11: "p_discharge", 16: "p_inv",
              17: "p_rec", 24: "p_eps", 26: "p_togrid", 27: "p_touser"}
        for reg, addr in FACTORY_SRC.items():
            e.uc.mem_write(addr, struct.pack("<I", SNAP[pw[reg]] & 0xFFFFFFFF))
        e.uc.mem_write(FACTORY_SEPS, struct.pack("<I", SNAP["s_eps"] & 0xFFFFFFFF))
        e.uc.mem_write(FACTORY_RUNTIME, struct.pack("<I", SNAP["runtime_s"] & 0xFFFFFFFF))
        out = {}
        for reg in list(SERVE_EXPECTED):
            try:
                out[reg] = e.call(GETTER, (reg,)) & 0xFFFF
            except Exception:
                out[reg] = None
        return out


class OursBackend:
    name = "ours"
    IR_P = 0x30000000      # scratch input-register image
    T_P  = 0x30002000      # scratch inv_telemetry_t

    def __init__(self, bin_path, elf_path):
        self.bin_path = bin_path
        self.elf_path = elf_path

    def _sim(self):
        from arm_sim import ArmSim, load_symbols_nm
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        sim = ArmSim(self.bin_path, load_symbols_nm(self.elf_path))
        sim.uc.mem_map(0x30000000, 0x4000)
        return sim

    def available(self):
        try:
            self._sim()
            return True
        except Exception:
            return False

    def serve(self):
        sim = self._sim()
        # pack inv_telemetry_t: 8 u32, u16 s_eps, 2 pad, 3 u32  (= 48 bytes)
        t = struct.pack("<8I H 2x 3I",
                        SNAP["p_pv1"], SNAP["p_pv2"], SNAP["p_pv3"], SNAP["p_charge"],
                        SNAP["p_discharge"], SNAP["p_inv"], SNAP["p_rec"], SNAP["p_eps"],
                        SNAP["s_eps"] & 0xFFFF,
                        SNAP["p_togrid"], SNAP["p_touser"], SNAP["runtime_s"])
        sim.wbytes(self.IR_P, bytes(0x200))
        sim.wbytes(self.T_P, t)
        sim.call("inv_telemetry_publish", (self.IR_P, self.T_P))
        regs = list(SERVE_EXPECTED) + list(OURS_EXTRA)
        return {r: struct.unpack("<H", sim.rbytes(self.IR_P + 2 * r, 2))[0] for r in regs}
