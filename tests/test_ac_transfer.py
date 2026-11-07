#!/usr/bin/env python3
"""Normal-mode AC-transfer decision -- factory oracle for the T14 spec (docs/18).

Drives the factory relay function `sub_08018a7c` (grid-eval path) in isolation on
the canonical 07 image -- enable set directly, clocked past the 50-tick debounce --
and asserts the settled PA12/PB3 commands follow the spec:

    enabled grid-ok -> (PA12=0, PB3=1);  enabled no-grid -> (1, 1);  disabled -> (0, 0)

Our firmware's pure `inv_ac_transfer_decide()` is held to the SAME vectors by the
toolchain-free host test tests/test_ac_transfer.c, so the factory oracle and our
reimplementation satisfy one shared spec (parity by contract). Factory-only here
because the pair is driven by a GPIO path, not a Modbus register.

Run (from repo root):
    python3 tests/test_ac_transfer.py                 # canonical 07 image if present
    python3 tests/test_ac_transfer.py FACTORY.bin
Or `make test-sim`. Skips cleanly without unicorn / a factory image.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from ac_transfer_contract import VECTORS, predict, FactoryBackend, B20  # noqa: E402

FACTORY_IMAGE = (sys.argv[1] if len(sys.argv) > 1 else None) \
    or os.environ.get("LXP_FACTORY_BIN") \
    or os.path.join(ROOT, "reference", "ceaa-07xx_vE_260214.bin")

_fac = []


def _factory_or_skip():
    if not _fac:
        _fac.append(FactoryBackend(FACTORY_IMAGE))
    fb = _fac[0]
    if not fb.available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    return fb


def test_factory_matches_spec():
    """The factory AC-transfer function drives PA12/PB3 per the enable + grid-state
    spec on every vector (and the vectors' `expected` agrees with predict())."""
    fb = _factory_or_skip()
    fails = []
    for label, enabled, grid, epa12, epb3 in VECTORS:
        assert predict(enabled, grid) == (epa12, epb3), "vector self-check: %s" % label
        got = fb.decide(enabled, grid)
        if got != (epa12, epb3):
            fails.append("%-26s en=%d grid=0x%08x -> %s, expected %s"
                         % (label, enabled, grid, got, (epa12, epb3)))
    assert not fails, "factory\n        " + "\n        ".join(fails)


def test_factory_transfer_debounce_is_50():
    """The transfer pair's PA12 switches behind a symmetric 50-tick debounce
    (the break-before-make sequencing, 0x2000dba4/5/6) -- qualified<->not both take
    50 calls to take effect. Characterizes the T14 sequencing timing."""
    fb = _factory_or_skip()
    off = fb.pa12_switch_delay(B20, 0)        # qualified -> not qualified
    on = fb.pa12_switch_delay(0, B20)         # not qualified -> qualified
    assert off == 50 and on == 50, \
        "expected 50/50-tick debounce, got off=%s on=%s" % (off, on)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    label = "factory=%s" % (os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("AC-transfer relay decision (T14)", label, globals()))
