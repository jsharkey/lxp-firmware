#!/usr/bin/env python3
"""Discharge-by-voltage hysteresis gate -- factory oracle for the T15 spec (docs/41).

Drives the factory ARM evaluator `sub_0801ed28` (voltage path) in isolation and
asserts its latched verdict follows the hysteresis spec `active = active ? v>=stop
: v>=start` on every vector. Our firmware's pure `inv_dischg_volt_gate()` is held
to the SAME vectors by the toolchain-free host test tests/test_dischg_gate.c, so
the factory oracle and our reimplementation satisfy one shared spec (parity by
contract). Factory-only here because the verdict is ARM-internal (consumed by the
control function sub_0801f438) -- there is no Modbus register for ours to serve.

Run (from repo root):
    python3 tests/test_dischg_gate.py                 # canonical 07 image if present
    python3 tests/test_dischg_gate.py FACTORY.bin
Or `make test-sim`. Skips cleanly without unicorn / a factory image.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from dischg_gate_contract import VECTORS, predict, FactoryBackend  # noqa: E402

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
    """The factory discharge-by-voltage gate follows the latched hysteresis spec
    (on at V>=start, off at V<stop) on every vector -- and the vectors' own
    `expected` agrees with the pure predict()."""
    fb = _factory_or_skip()
    fails = []
    for label, prev, vbat, expected in VECTORS:
        assert predict(prev, vbat) == expected, "vector self-check: %s" % label
        got = fb.verdict(prev, vbat)
        if got != expected:
            fails.append("%-24s prev=%d V=%d -> %s, expected %s"
                         % (label, prev, vbat, got, expected))
    assert not fails, "factory\n        " + "\n        ".join(fails)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    label = "factory=%s" % (os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("discharge-by-voltage hysteresis gate (T15)", label, globals()))
