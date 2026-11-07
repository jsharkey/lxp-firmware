#!/usr/bin/env python3
"""Shared normal-mode AC-transfer contract (docs/18, T14).

Once the AC-transfer feature is *enabled*, the factory relay function
`sub_08018a7c` (grid-eval path, canonical 07 image) drives the PA12/PB3 transfer
pair from the DSP grid-status word:

    enabled == false              -> PA12 = 0, PB3 = 0   (both open)
    enabled, grid qualified       -> PA12 = 0, PB3 = 1
    enabled, grid NOT qualified   -> PA12 = 1, PB3 = 1

where the grid is qualified iff `0x2000ce5c+0xbc` **bit 20 is set AND bits 29-30
!= 2**. The enable is `0x2000d9ca` bit 3 (derived by `sub_0801887c`; the earlier
T14 hand-off stalled trying to set it through the deriver in the full RTOS loop —
an *isolated* oracle call sets it directly, which is what this does). The pair's
drivers are `sub_08033536` (PB3, GPIOB bit 3) and `sub_080334fc` (PA12, GPIOA bit
12); the switching is staged behind three 50-tick debounces (`0x2000dba4/5/6`), so
the oracle clocks the function past them and reads the settled command.

Our firmware's pure `inv_ac_transfer_decide()` is held to the SAME vectors by the
toolchain-free host test tests/test_ac_transfer.c.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Canonical 07 image addresses (docs/18, T14; reference/README.md).
FN       = 0x08018a7c        # the PA12/PB3 relay function
D0E4     = 0x2000d0e4        # STATUS struct (manual flag at +0xa9)
CE5C     = 0x2000ce5c        # DSP telemetry (grid-status word at +0xbc)
D9CA     = 0x2000d9ca        # enable byte (bit 3 = AC-transfer enable)
PB3_FN   = 0x08033536        # drives PB3 (GPIOB bit 3)
PA12_FN  = 0x080334fc        # drives PA12 (GPIOA bit 12)
CLOCKS   = 70                # > the 50-tick debounce, so the pair settles

B20 = 1 << 20


def _mode(n):
    return (n & 3) << 29


# (label, enabled, dsp_grid, exp_pa12, exp_pb3)
VECTORS = [
    ("disabled",                 False, 0,               0, 0),
    ("disabled + grid ok",       False, B20,             0, 0),
    ("enabled grid-ok bit20",    True,  B20,             0, 1),
    ("enabled grid-ok mode1",    True,  B20 | _mode(1),  0, 1),
    ("enabled grid-ok mode3",    True,  B20 | _mode(3),  0, 1),
    ("enabled no-grid bit20clr", True,  0,               1, 1),
    ("enabled grid mode2 bad",   True,  B20 | _mode(2),  1, 1),
    ("enabled bit20clr mode1",   True,  _mode(1),        1, 1),
]


def predict(enabled, dsp_grid):
    """The pure spec both sides must satisfy (mirrors inv_ac_transfer_decide)."""
    if not enabled:
        return (0, 0)
    grid_ok = bool(dsp_grid & B20) and (((dsp_grid >> 29) & 3) != 2)
    return (0 if grid_ok else 1, 1)


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

    def decide(self, enabled, dsp_grid):
        """Drive sub_08018a7c (enable set directly, isolated), clock it past the
        debounce, and return the last (PA12, PB3) commands its setters issued."""
        from emu import Emu
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(D0E4 + 0xa9, bytes([0]))          # not manual/AutoTest
        cmd = {}

        def hook(uc, addr, size, ud):
            if addr == PB3_FN:
                cmd["pb3"] = uc.reg_read(UC_ARM_REG_R0) & 1
            elif addr == PA12_FN:
                cmd["pa12"] = uc.reg_read(UC_ARM_REG_R0) & 1
        e.uc.hook_add(UC_HOOK_CODE, hook, begin=min(PB3_FN, PA12_FN), end=max(PB3_FN, PA12_FN) + 2)

        import contextlib
        import io
        for _ in range(CLOCKS):
            e.uc.mem_write(D9CA, bytes([1 << 3 if enabled else 0]))   # re-assert each pass
            e.uc.mem_write(CE5C + 0xbc, struct.pack("<I", dsp_grid & 0xFFFFFFFF))
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    e.call(FN)
                except Exception:
                    pass
        return (cmd.get("pa12"), cmd.get("pb3"))

    def decide_via_dsp_enable(self, dsp_grid):
        """Like decide(enabled=True, ...) but enable the transfer via the
        **DSP-provided** bit `0x2000ce5c+0xca` bit 4 (not the ARM `d9ca` bit 3),
        proving that DSP bit is an equivalent enable. Returns (PA12, PB3)."""
        from emu import Emu
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0
        import contextlib
        import io
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(D0E4 + 0xa9, bytes([0]))
        cmd = {}

        def hook(uc, addr, size, ud):
            if addr == PB3_FN:
                cmd["pb3"] = uc.reg_read(UC_ARM_REG_R0) & 1
            elif addr == PA12_FN:
                cmd["pa12"] = uc.reg_read(UC_ARM_REG_R0) & 1
        e.uc.hook_add(UC_HOOK_CODE, hook, begin=min(PB3_FN, PA12_FN), end=max(PB3_FN, PA12_FN) + 2)
        for _ in range(CLOCKS):
            e.uc.mem_write(D9CA, bytes([0]))                     # ARM enable OFF
            v = struct.unpack("<H", e.rbytes(CE5C + 0xca, 2))[0] | (1 << 4)
            e.uc.mem_write(CE5C + 0xca, struct.pack("<H", v))    # DSP enable bit 4 ON
            e.uc.mem_write(CE5C + 0xbc, struct.pack("<I", dsp_grid & 0xFFFFFFFF))
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    e.call(FN)
                except Exception:
                    pass
        return (cmd.get("pa12"), cmd.get("pb3"))

    def pa12_switch_delay(self, from_grid, to_grid):
        """Settle the pair at `from_grid`, then flip the DSP grid word to `to_grid`
        and count how many calls until PA12 changes -- the break-before-make
        debounce (`0x2000dba4/5/6`, 50-tick). Returns the call count, or None."""
        from emu import Emu
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0
        import contextlib
        import io
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(D0E4 + 0xa9, bytes([0]))
        cur = {}

        def hook(uc, addr, size, ud):
            if addr == PA12_FN:
                cur["pa12"] = uc.reg_read(UC_ARM_REG_R0) & 1
        e.uc.hook_add(UC_HOOK_CODE, hook, begin=PA12_FN, end=PA12_FN + 2)

        def step(grid):
            e.uc.mem_write(D9CA, bytes([1 << 3]))
            e.uc.mem_write(CE5C + 0xbc, struct.pack("<I", grid & 0xFFFFFFFF))
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    e.call(FN)
                except Exception:
                    pass
        for _ in range(CLOCKS):           # settle at the starting grid state
            step(from_grid)
        settled = cur.get("pa12")
        cur["pa12"] = None
        for i in range(1, CLOCKS):        # flip and count calls until PA12 moves
            step(to_grid)
            if cur.get("pa12") is not None and cur["pa12"] != settled:
                return i
        return None
