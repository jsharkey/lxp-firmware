#!/usr/bin/env python3
"""Focused time-window micro-tests (docs/35) -- the SAME vectors, factory-vs-ours.

A small, cheap complement to the full-simulator suite: it does not boot an image
or speak Modbus. It drives only the AC-First "is the clock inside a window now?"
evaluator, two ways:

  * our compiled acfirst_window_active() (src/sched/acfirst.c) via ctypes, and
  * the factory ARM evaluator called in isolation under Unicorn (RTC + window
    registers seeded, nothing else) -- the tools/emu_acfirst.py recipe, reduced.

Run (from repo root):
    python3 tests/test_timewindow.py                       # ours; factory if available
    python3 tests/test_timewindow.py path/to/factory.bin   # name the factory image
    python3 tests/test_timewindow.py --profile ceaa07 img.bin   # force a profile
Or: `make test-window`. The factory image profile is auto-detected by default
(works for the 05-series and 07-series images alike).

Ours always runs (needs only host `cc`). The factory half SKIPS cleanly when
unicorn or the (proprietary, never-committed) image is absent.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip          # noqa: E402
from timewindow_contract import VECTORS, OursBackend, FactoryBackend  # noqa: E402


# --- argv: optional factory image + profile ---------------------------------
def _parse(argv):
    image, symbols, profile, positional = None, None, "auto", []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--symbols":
            symbols = argv[i + 1]; i += 2
        elif a.startswith("--symbols="):
            symbols = a.split("=", 1)[1]; i += 1
        elif a == "--profile":
            profile = argv[i + 1]; i += 2
        elif a.startswith("--profile="):
            profile = a.split("=", 1)[1]; i += 1
        else:
            positional.append(a); i += 1
    if positional:
        image = positional[0]
    image = image or os.environ.get("LXP_FACTORY_BIN") \
        or os.path.join(ROOT, "reference", "com_flat.bin")
    return image, symbols, profile


FACTORY_IMAGE, SYMBOLS, PROFILE = _parse(sys.argv[1:])

_ours_cache = []


def _ours():
    if not _ours_cache:
        _ours_cache.append(OursBackend())
    return _ours_cache[0]


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
    ob = _ours()
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
    """Our compiled acfirst_window_active() satisfies the window spec."""
    _check_against_spec(_ours())


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
    label = "ours=acfirst.c  factory=%s" % (
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("time-window micro-contract (AC-First + AC-charge)", label, globals()))
