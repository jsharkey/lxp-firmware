#!/usr/bin/env python3
"""Generator-charge-by-voltage gate -- factory oracle for the T16 spec (docs HR194_198).

Drives the factory generator-charge evaluator's voltage block `0x08035086 …
0x080350dc` (verdict byte `0x2000dbc0`) in isolation on the canonical 07 image --
settings base in r1, the thresholds / battery voltage / stop-confirm bits seeded
directly, clocked once -- and asserts the latched verdict follows the charge-direction
hysteresis spec:

    off: charge ON  when Vbat <  start_v (HR194 / settings +0xac)
    on:  charge OFF when Vbat >= end_v   (HR195 / settings +0xae) AND stop_ok

Our firmware's pure `inv_gen_charge_volt_gate()` is held to the SAME vectors by the
toolchain-free host test tests/test_gen_charge.c, so the factory oracle and our
reimplementation satisfy one shared spec (parity by contract).

Run (from repo root):
    python3 tests/test_gen_charge.py                  # canonical 07 image if present
    python3 tests/test_gen_charge.py FACTORY.bin
Or `make test-sim`. Skips cleanly without unicorn / a factory image.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                             # noqa: E402
from gen_charge_contract import (VECTORS, predict, FactoryBackend,     # noqa: E402
                                 SOC_VECTORS, predict_soc)

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
    """The factory gen-charge voltage block latches its verdict per the
    charge-direction hysteresis on every vector (and the vectors' `expected`
    agrees with predict())."""
    fb = _factory_or_skip()
    fails = []
    for label, prev, vbat, stop_ok, expected in VECTORS:
        assert predict(prev, vbat, stop_ok) == expected, "vector self-check: %s" % label
        got = fb.verdict(prev, vbat, stop_ok)
        if got != expected:
            fails.append("%-26s prev=%d v=%d stop_ok=%d -> %s, expected %s"
                         % (label, prev, vbat, stop_ok, got, expected))
    assert not fails, "factory\n        " + "\n        ".join(fails)


def test_factory_stop_needs_confirm():
    """Above end_v the gate stays ON until the DSP stop-confirm bits are set
    (bank+0xb6 bit11 AND bank+0xbc bit15) -- characterizes the extra stop
    condition found in the block (T16)."""
    fb = _factory_or_skip()
    assert fb.verdict(True, 490, False) is True, "no confirm: stays charging above end"
    assert fb.verdict(True, 490, True) is False, "with confirm: stops above end"


def test_factory_soc_matches_spec():
    """The factory gen-charge-by-SOC block (verdict 0x2000dbc1) latches per the same
    charge-direction hysteresis on the battery SOC byte (GenChargeType = 1), on every
    vector. The SOC sibling of the voltage gate (T16)."""
    fb = _factory_or_skip()
    fails = []
    for label, prev, soc, stop_ok, expected in SOC_VECTORS:
        assert predict_soc(prev, soc, stop_ok) == expected, "vector self-check: %s" % label
        got = fb.verdict_soc(prev, soc, stop_ok)
        if got != expected:
            fails.append("%-26s prev=%d soc=%d stop_ok=%d -> %s, expected %s"
                         % (label, prev, soc, stop_ok, got, expected))
    assert not fails, "factory\n        " + "\n        ".join(fails)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    label = "factory=%s" % (os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("Generator-charge voltage gate (T16)", label, globals()))
