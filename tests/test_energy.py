#!/usr/bin/env python3
"""Accumulated energy input registers (IR 28-37 / 40-59) -- same spec, factory vs ours.

Drives each image's own energy accumulator and reads Epv1_day (IR 28) / Epv1_all
(IR 40/41): the factory's real accumulator (fn 0x0801fbc4 + input getter
0x0803289c) and our firmware's energy_tick()/energy_publish() (by symbol). Both
must satisfy the shared ENERGY_VECTORS. Extra credit: our daily counter resets at
a midnight RTC boundary while the cumulative counter persists. See
energy_contract.py and docs/37.

Run (from repo root):
    python3 tests/test_energy.py                              # factory if present
    python3 tests/test_energy.py FACTORY.bin                  # name the image
    python3 tests/test_energy.py --ours-bin B --ours-elf E    # our firmware build
Or `make test-sim`. Each half SKIPs cleanly when unicorn / a built firmware / the
proprietary factory image is absent. Needs `pip install unicorn`.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from energy_contract import (ENERGY_VECTORS, ROLLOVER_VECTORS, SEED_DAILY,
                             SEED_ALL, FactoryBackend, OursBackend)  # noqa: E402


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


def _check(backend):
    fails = []
    for label, power, nticks, state, exp_day, exp_all in ENERGY_VECTORS:
        day, allv = backend.accumulate(power, nticks, state)
        if (day, allv) != (exp_day, exp_all):
            fails.append("%-22s P=%d x%d st=0x%02x -> day=%d all=%d, expected day=%d all=%d"
                         % (label, power, nticks, state, day, allv, exp_day, exp_all))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


def test_factory_epv1_accumulates():
    """Factory: Epv1_all (IR 40) and Epv1_day (IR 28) count up as power is
    integrated over ticks, gated on a running state -- the shared spec."""
    _check(_factory_or_skip())


def test_ours_epv1_accumulates():
    """Our energy_tick()/energy_publish() reproduces the factory accumulator
    exactly (same threshold, half-rate, gate) -- same spec as the oracle."""
    _check(_ours_or_skip())


def _check_rollover(backend):
    fails = []
    for label, prev_day, new_day, should_reset in ROLLOVER_VECTORS:
        day, allv = backend.rollover(prev_day, new_day)
        exp_day = 0 if should_reset else SEED_DAILY
        if (day, allv) != (exp_day, SEED_ALL):
            fails.append("%-20s %d->%d -> Epv1_day=%d Epv1_all=%d, expected day=%d all=%d"
                         % (label, prev_day, new_day, day, allv, exp_day, SEED_ALL))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


def test_factory_epv1_day_resets_at_midnight():
    """Factory: the calendar-date reset detector (0x08037cb2) zeroes the daily
    counter (IR 28) when the RTC day-of-month changes, while the cumulative
    counter (IR 40) persists; same day keeps both -- the shared rollover spec."""
    _check_rollover(_factory_or_skip())


def test_ours_epv1_day_resets_at_midnight():
    """Our energy_rollover() zeroes the daily counters on a day change and leaves
    the cumulative counters -- same spec as the factory oracle."""
    _check_rollover(_ours_or_skip())


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("accumulated energy counters (IR 28-37 / 40-59)", label, globals()))
