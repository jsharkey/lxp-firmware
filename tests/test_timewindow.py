#!/usr/bin/env python3
"""Focused time-window micro-tests (docs/35) -- the SAME vectors, factory-vs-ours.

A small, cheap complement to the full-simulator suite: it does not boot an image
or speak Modbus. It drives only the time-window "is the clock inside a window
now?" evaluators, calling ONE function in isolation under Unicorn -- the SAME
strategy for both firmwares:

  * ours    -- our firmware's acfirst_window_active(), resolved by SYMBOL from
               build/firmware.elf and called through the real ARM calling
               convention (so our code runs exactly as the firmware runs it).
  * factory -- the factory ARM evaluator (AC-First / AC-charge), seeded with only
               the RTC + window registers -- the tools/emu_acfirst.py recipe.

Run (from repo root):
    python3 tests/test_timewindow.py                       # factory if available
    python3 tests/test_timewindow.py path/to/factory.bin   # name the factory image
    python3 tests/test_timewindow.py --profile ceaa07 img.bin   # force a profile
    python3 tests/test_timewindow.py --ours-bin B --ours-elf E   # our firmware build
Or: `make test-window` (builds our firmware first). The factory image profile is
auto-detected by default (works for the 05-series and 07-series images alike).

Both halves run under Unicorn: each SKIPS cleanly when unicorn, a built firmware
(ours), or the proprietary never-committed factory image is absent. (Host-only,
toolchain-free coverage of the pure function lives in tests/test_acfirst.c.)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip          # noqa: E402
from timewindow_contract import VECTORS, OursBackend, FactoryBackend  # noqa: E402


# --- argv: optional factory image + profile + our firmware paths ------------
def _parse(argv):
    image = symbols = ours_bin = ours_elf = None
    profile, positional = "auto", []
    i = 0
    while i < len(argv):
        a = argv[i]
        for opt in ("--symbols", "--profile", "--ours-bin", "--ours-elf"):
            if a == opt:
                val = argv[i + 1]; i += 2; break
            if a.startswith(opt + "="):
                val = a.split("=", 1)[1]; i += 1; break
        else:
            positional.append(a); i += 1; continue
        if opt == "--symbols":
            symbols = val
        elif opt == "--profile":
            profile = val
        elif opt == "--ours-bin":
            ours_bin = val
        elif opt == "--ours-elf":
            ours_elf = val
    if positional:
        image = positional[0]
    image = image or os.environ.get("LXP_FACTORY_BIN") \
        or os.path.join(ROOT, "reference", "com_flat.bin")
    return image, symbols, profile, ours_bin, ours_elf


FACTORY_IMAGE, SYMBOLS, PROFILE, OURS_BIN, OURS_ELF = _parse(sys.argv[1:])

_ours_cache = []


def _ours():
    if not _ours_cache:
        _ours_cache.append(OursBackend(OURS_BIN, OURS_ELF))
    return _ours_cache[0]


def _ours_or_skip():
    ob = _ours()
    if not ob.available():
        raise Skip("needs unicorn + a built firmware (run `make`)")
    return ob


def _factory_or_skip(window_type):
    fb = FactoryBackend(FACTORY_IMAGE, SYMBOLS, window_type=window_type, profile=PROFILE)
    if not fb.available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    return fb


def _check_against_spec(backend):
    fails = []
    for name, windows, hour, minute, expected in VECTORS:
        got = backend.active(windows, hour, minute)
        if got != expected:
            fails.append("%02d:%02d %-28s expected %s, got %s"
                         % (hour, minute, name, expected, got))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


def _agrees_with_ours(backend):
    ob = _ours_or_skip()
    diffs = []
    for name, windows, hour, minute, _expected in VECTORS:
        f = backend.active(windows, hour, minute)
        o = ob.active(windows, hour, minute)
        if f != o:
            diffs.append("%02d:%02d %-28s factory=%s ours=%s"
                         % (hour, minute, name, f, o))
    assert not diffs, "%s\n        " % backend.name + "\n        ".join(diffs)


# --- the tests (ONE set of vectors, each backend / window type) -------------
# Our acfirst_window_active() is a generic start-incl/end-excl/wrap predicate, so
# it is the oracle for EVERY factory window evaluator.
def test_ours_matches_spec():
    """Our acfirst_window_active() (under Unicorn, by symbol) satisfies the spec."""
    _check_against_spec(_ours_or_skip())


def test_acfirst_factory_matches_spec():
    """The factory AC-First evaluator (HR152-157), in isolation, matches the spec."""
    _check_against_spec(_factory_or_skip("acfirst"))


def test_acfirst_factory_agrees_with_ours():
    """Factory AC-First evaluator and our firmware agree on every vector."""
    _agrees_with_ours(_factory_or_skip("acfirst"))


def test_acchg_factory_matches_spec():
    """The factory AC-charge evaluator (HR68-73), in isolation, matches the spec."""
    _check_against_spec(_factory_or_skip("acchg"))


def test_acchg_factory_agrees_with_ours():
    """Factory AC-charge evaluator and our firmware agree on every vector --
    i.e. the AC-charge windows share AC-First's window semantics."""
    _agrees_with_ours(_factory_or_skip("acchg"))


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = _ours().available()
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN or "build/firmware.bin") if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("time-window micro-contract (AC-First + AC-charge)", label, globals()))
