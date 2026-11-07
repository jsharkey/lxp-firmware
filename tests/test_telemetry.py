#!/usr/bin/env python3
"""ARM-computed telemetry serve -- the SAME spec, factory-vs-ours.

Injects the ARM's internal computed quantities and reads the served dongle input
registers (powers /10, Seps 1:1, RunningTime split). Both images must produce
SERVE_EXPECTED. See telemetry_contract.py, docs/39 T07, docs/22.

Run (from repo root):
    python3 tests/test_telemetry.py                            # factory if present
    python3 tests/test_telemetry.py FACTORY.bin                # name the image
    python3 tests/test_telemetry.py --ours-bin B --ours-elf E  # our firmware build
Or `make test-sim`. Each half SKIPs cleanly when unicorn / a built firmware / the
proprietary factory image is absent. (The pure-function host test is
tests/test_telemetry.c, run by `make test`.)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from telemetry_contract import (SERVE_EXPECTED, OURS_EXTRA,
                                FactoryBackend, OursBackend)     # noqa: E402


def _parse(argv):
    image = ours_bin = ours_elf = None
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
        for opt in ("--ours-bin", "--ours-elf"):
            if a == opt:
                val = argv[i + 1]; i += 2; break
            if a.startswith(opt + "="):
                val = a.split("=", 1)[1]; i += 1; break
        else:
            positional.append(a); i += 1; continue
        if opt == "--ours-bin":
            ours_bin = val
        else:
            ours_elf = val
    if positional:
        image = positional[0]
    image = image or os.environ.get("LXP_FACTORY_BIN") \
        or os.path.join(ROOT, "reference", "ceaa-05xx_com_vE_250325.bin")
    return image, ours_bin, ours_elf


FACTORY_IMAGE, OURS_BIN, OURS_ELF = _parse(sys.argv[1:])
_fac, _ours = [], []


def _factory_or_skip():
    if not _fac:
        _fac.append(FactoryBackend(FACTORY_IMAGE))
    fb = _fac[0]
    if not fb.available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    return fb


def _ours_or_skip():
    if not _ours:
        _ours.append(OursBackend(OURS_BIN, OURS_ELF))
    ob = _ours[0]
    if not ob.available():
        raise Skip("needs unicorn + a built firmware (pass --ours-bin/--ours-elf; run `make`)")
    return ob


def _fmt(got, exp):
    return "\n        ".join("IR %-3d got %s, expected %s" % (r, got.get(r), exp[r])
                             for r in sorted(exp) if got.get(r) != exp[r])


def test_factory_telemetry_served():
    """Factory: injected internal powers/Seps/runtime are served scaled (powers
    /10, Seps 1:1, RunningTime split) -- the shared spec."""
    got = _factory_or_skip().serve()
    bad = _fmt(got, SERVE_EXPECTED)
    assert not bad, "factory\n        " + bad


def test_ours_telemetry_served():
    """Our inv_telemetry_publish() serves the same registers with the same scaling
    (plus Ppv3 on a 3-MPPT build) -- same spec as the oracle."""
    exp = dict(SERVE_EXPECTED); exp.update(OURS_EXTRA)
    got = _ours_or_skip().serve()
    bad = _fmt(got, exp)
    assert not bad, "ours\n        " + bad


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("ARM-computed telemetry (powers / Seps / runtime)", label, globals()))
