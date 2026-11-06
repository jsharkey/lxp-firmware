#!/usr/bin/env python3
"""HR write-validation semantics -- the SAME spec, factory-vs-ours.

Drives a holding-register write over the Modbus dongle on each image and checks
the reply: echo (accepted) vs Modbus exception (rejected, with code). Both images
must give the verdict in WRITE_VECTORS -- so an out-of-range write is rejected
with exception 3 (not clamped, not stored), and a read-only register with
exception 4. See settings_contract.py, docs/39 T04, and docs/31 for the one-sided
range quirks that are replicated for parity.

Run (from repo root):
    python3 tests/test_settings_validate.py                           # factory if present
    python3 tests/test_settings_validate.py FACTORY.bin               # name the image
    python3 tests/test_settings_validate.py --ours-bin B --ours-elf E # our firmware build
Or `make test-sim`. Each half SKIPs cleanly when unicorn / a built firmware / the
proprietary factory image is absent. Needs `pip install unicorn`.

(The pure-function host test is tests/test_settings_validate.c, run by `make test`.)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from settings_contract import WRITE_VECTORS, FactoryBackend, OursBackend  # noqa: E402


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
        or os.path.join(ROOT, "reference", "com_flat.bin")
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


def _check(backend):
    fails = []
    for label, reg, val, expect in WRITE_VECTORS:
        got = backend.write_verdict(reg, val)
        if got != expect:
            fails.append("%-32s HR%d=%d -> %s, expected %s" % (label, reg, val, got, expect))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


def test_factory_write_semantics():
    """Factory: out-of-range HR writes are rejected with a Modbus exception (not
    clamped/stored), read-only registers with exception 4 -- the shared spec."""
    _check(_factory_or_skip())


def test_ours_write_semantics():
    """Our settings_validate() in front of mb_wr_hold reproduces the factory's
    accept/reject verdicts -- same spec as the oracle."""
    _check(_ours_or_skip())


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("HR write semantics (ranges / rejects / read-only)", label, globals()))
