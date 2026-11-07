#!/usr/bin/env python3
"""Whole-HR write-semantics sweep (docs/39 T24).

For every holding register with a documented range, writes the four boundary
vectors (min-1 / min / max / max+1) and the read-only version registers on a fresh
boot and records the factory's verdict, then checks our firmware gives the SAME
verdict (settings_validate parity). The committed verdicts are in wrsem_expected.py
and the deviations from the naive spec are in docs/31. See wrsem_contract.py.

SLOW: fresh boot per vector, both images (minutes). Run with `make wrsem`, not in
the default suites.

    python3 tests/test_wrsem_sweep.py FACTORY.bin --ours-bin B --ours-elf E
    python3 tests/test_wrsem_sweep.py ... --dump        # print the verdict table
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                        # noqa: E402
from settings_contract import FactoryBackend, OursBackend         # noqa: E402
import wrsem_contract as W                                        # noqa: E402
import wrsem_expected as EXP                                      # noqa: E402


def _parse(argv):
    image = ours_bin = ours_elf = None
    positional, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--dump":
            i += 1; continue
        for opt in ("--ours-bin", "--ours-elf", "--symbols"):
            if a == opt:
                val = argv[i + 1]; i += 2; break
            if a.startswith(opt + "="):
                val = a.split("=", 1)[1]; i += 1; break
        else:
            positional.append(a); i += 1; continue
        if opt == "--ours-bin":
            ours_bin = val
        elif opt == "--ours-elf":
            ours_elf = val
    if positional:
        image = positional[0]
    image = image or os.environ.get("LXP_FACTORY_BIN") \
        or os.path.join(ROOT, "reference", "com_flat.bin")
    return image, ours_bin, ours_elf


FACTORY_IMAGE, OURS_BIN, OURS_ELF = _parse(sys.argv[1:])
_cache = {}


def _sweep(which):
    if which not in _cache:
        if which == "factory":
            b = FactoryBackend(FACTORY_IMAGE)
            if not b.available():
                raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
        else:
            b = OursBackend(OURS_BIN, OURS_ELF)
            if not b.available():
                raise Skip("needs unicorn + a built firmware (--ours-bin/--ours-elf)")
        _cache[which] = W.sweep(b)
    return _cache[which]


def test_factory_verdicts_match_committed():
    """The factory's verdict for every boundary vector matches the committed table
    (wrsem_expected.FACTORY). Pins the real write-validation surface so a factory
    re-pin or image change is caught; the deviations from the naive spec are
    annotated there and in docs/31."""
    fac = _sweep("factory")
    drift = {("HR%d" % r, v): (got, EXP.FACTORY.get("%d:%d" % (r, v)))
             for (r, v), got in fac.items()
             if got != EXP.FACTORY.get("%d:%d" % (r, v))}
    assert not drift, "factory verdict drift vs wrsem_expected.py: %s" % drift


def test_ours_matches_factory():
    """Our firmware's settings_validate gives the SAME verdict as the factory for
    every vector (parity). Any intentional divergence must be recorded as a quirk
    in wrsem_expected.OURS_DEVIATIONS with a docs/31 reference."""
    fac, ours = _sweep("factory"), _sweep("ours")
    bad = []
    for key in sorted(fac):
        fv, ov = fac[key], ours.get(key)
        if fv != ov and key not in EXP.OURS_DEVIATIONS:
            bad.append("HR%d v=%d: factory=%s ours=%s" % (key[0], key[1], fv, ov))
    assert not bad, "ours != factory (unrecorded):\n  " + "\n  ".join(bad)


if __name__ == "__main__":
    if "--dump" in sys.argv:
        fac = _sweep("factory")
        try:
            ours = _sweep("ours")
        except Skip:
            ours = {}
        for (r, v) in sorted(fac):
            o = ours.get((r, v), "-")
            flag = "" if o == fac[(r, v)] or o == "-" else "  <-- DIFF"
            print("HR%-3d v=%-6d factory=%-10s ours=%s%s" % (r, v, fac[(r, v)], o, flag))
        sys.exit(0)
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (os.path.basename(OURS_BIN) if ours_ok else "(skip)",
                                     os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("whole-HR write-semantics sweep", label, globals()))
