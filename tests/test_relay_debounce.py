#!/usr/bin/env python3
"""PD11 dry-contact relay debounce -- factory micro-test (docs/18, T14).

The T14 roadmap scoped PC5 (gen/AC-couple) and PD11 (dry-contact) as *timing*
micro-tests, not oracle-vector reimplementations: they are change-detection +
debounce behaviours, not clean state->relay maps (so ours mirrors no verdict
table for them). This locks the one that drives cleanly in isolation -- **PD11**
(`sub_08035ef2`, GPIO setter `sub_08033556` = GPIOD bit 11).

Driven on the canonical 07 image: PD11 gates on the DSP grid/EPS status bit
`0x2000ce5c + 0xc4` **bit 1**, and only ever *closes* (=1) -- under bit 1 **set**
it latches `0x2000d9c8` bit 10 and closes after ~10 ticks; under bit 1 **clear** it
closes via the `0x2000da3a` bit 1 path after ~25. Characterizes the debounce and
confirms the "only ever closes" decode (docs/18). Factory-only (GPIO path, no
Modbus register, and no ours reimplementation to hold to a contract).

Run (from repo root):
    python3 tests/test_relay_debounce.py                 # canonical 07 image if present
    python3 tests/test_relay_debounce.py FACTORY.bin
Or `make test-sim`. Skips cleanly without unicorn / a factory image.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from arm_sim_runner import run_tests, Skip                      # noqa: E402

FACTORY_IMAGE = (sys.argv[1] if len(sys.argv) > 1 else None) \
    or os.environ.get("LXP_FACTORY_BIN") \
    or os.path.join(ROOT, "reference", "ceaa-07xx_vE_260214.bin")

# Canonical 07 image addresses (docs/18, T14).
FN      = 0x08035ef2        # PD11 relay function
SETTER  = 0x08033556        # GPIOD bit 11 command setter (r0 = level)
CE5C    = 0x2000ce5c        # DSP telemetry bank (grid/EPS status at +0xc4)
CLOCKS  = 40               # > the 10/25-tick debounce sub-thresholds


def _available():
    try:
        from emu import Emu  # noqa: F401
    except Exception:
        return False
    return os.path.exists(FACTORY_IMAGE)


def _close_tick(bit1):
    """Drive sub_08035ef2 with +0xc4 bit 1 set/clear each pass, clocking past the
    debounce; return (final_pd11_level, tick_at_which_it_first_closed)."""
    from emu import Emu
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0
    import contextlib
    import io
    e = Emu(FACTORY_IMAGE, os.path.join(ROOT, "reference", "symbols.csv"))
    cmd = {}

    def hook(uc, addr, size, ud):
        if addr == SETTER:
            cmd["v"] = uc.reg_read(UC_ARM_REG_R0) & 1
    e.uc.hook_add(UC_HOOK_CODE, hook, begin=SETTER, end=SETTER + 2)

    first = None
    for i in range(1, CLOCKS + 1):
        v = e.rbytes(CE5C + 0xc4, 1)[0]
        v = (v | 2) if bit1 else (v & ~2)
        e.uc.mem_write(CE5C + 0xc4, bytes([v]))
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                e.call(FN)
            except Exception:
                pass
        if cmd.get("v") == 1 and first is None:
            first = i
    return cmd.get("v"), first


def test_pd11_closes_under_grid_bit_after_debounce():
    """With the DSP grid/EPS bit (+0xc4 bit 1) SET, PD11 closes (=1) after the
    ~10-tick debounce (the d9c8-bit10 latch path)."""
    if not _available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    level, tick = _close_tick(True)
    assert level == 1, "PD11 did not end closed under +0xc4 bit 1 set"
    assert tick == 10, "expected PD11 to close at the ~10-tick debounce, got %s" % tick


def test_pd11_closes_under_bit_clear_after_longer_debounce():
    """With +0xc4 bit 1 CLEAR, PD11 still only ever *closes* -- via the da3a-bit1
    path after the longer ~25-tick debounce (confirms the "only ever closes"
    decode, docs/18)."""
    if not _available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    level, tick = _close_tick(False)
    assert level == 1, "PD11 did not end closed under +0xc4 bit 1 clear"
    assert tick == 25, "expected PD11 to close at the ~25-tick debounce, got %s" % tick


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    label = "factory=%s" % (os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("PD11 dry-contact relay debounce (T14)", label, globals()))
