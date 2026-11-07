#!/usr/bin/env python3
"""Whole-surface read sweep + parity scoreboard (docs/39 T23).

Sweeps every dongle register (IR 0-159, IR 5000-5126, HR 0-255) on each image in
spec-legal chunks and diffs ours vs the factory into the parity scoreboard. See
regsweep_contract.py for the seed/sweep mechanics and the committed classification
in regsweep_expected.py / docs/wiring/ARM-UART5-dongle/regsweep-scoreboard.md.

Run (from repo root):
    python3 tests/test_regsweep.py                              # factory if present
    python3 tests/test_regsweep.py FACTORY.bin --ours-bin B --ours-elf E
    python3 tests/test_regsweep.py ... --dump                   # print the scoreboard
Or `make regsweep`. SKIPs cleanly without unicorn / a built firmware / the image.
Slow: it seeds and warm-clones each image once (minutes).
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                       # noqa: E402
from regsweep_contract import FactoryBackend, OursBackend, FRAMING  # noqa: E402
import regsweep_expected as EXP                                  # noqa: E402

PERPACK = range(5000, 5127)


def _parse(argv):
    image = ours_bin = ours_elf = None
    positional = []
    i = 0
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


def _ours():
    if "o" not in _cache:
        b = OursBackend(OURS_BIN, OURS_ELF)
        if not b.available():
            raise Skip("needs unicorn + a built firmware (--ours-bin/--ours-elf; run `make`)")
        _cache["o"] = b.sweep()
    return _cache["o"]


def _factory():
    if "f" not in _cache:
        b = FactoryBackend(FACTORY_IMAGE)
        if not b.available():
            raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
        _cache["f"] = b.sweep()
    return _cache["f"]


# --- ours: the whole surface has a fixed, enforced shape --------------------
def test_ours_surface_shape():
    """Our firmware serves every spec register (IR 0-159, HR 0-255) and rejects
    the per-pack block IR 5000-5126 (not implemented) with exception 2 -- no
    register silently drops. Pins our whole-surface shape."""
    surface, _fr = _ours()
    bad = []
    for (space, num), r in sorted(surface.items()):
        if space == "IR" and num in PERPACK:
            ok = r == ("exc", 2)
        else:
            ok = r[0] == "ok"
        if not ok:
            bad.append("%s%d=%s" % (space, num, r))
    assert not bad, "ours surface shape: %s" % bad[:20]


def test_ours_framing_enforced():
    """Our firmware enforces the documented dongle framing rule: a read crossing a
    40-group boundary, longer than 40, zero-length, or out of map -> exception 2."""
    _s, fr = _ours()
    bad = [(k, v) for k, v in fr.items() if v != ("exc", 2)]
    assert not bad, "ours should reject these framings with exc 2: %s" % bad


# --- factory (USART3 fallback slave): lenient framing, serves per-pack ------
def test_factory_framing_lenient():
    """The factory's USART3 fallback slave (the port the harness reaches -- not the
    real UART5 dongle handler, a T02 task) does NOT enforce the framing rule: all
    four framings are served, not rejected. Documents the asymmetry so a future
    change is deliberate."""
    _s, fr = _factory()
    bad = [(k, v) for k, v in fr.items() if v[0] != "ok"]
    assert not bad, "factory USART3 slave expected lenient (ok) framing, got: %s" % bad


def test_factory_serves_perpack():
    """The factory serves the per-pack block IR 5000-5126 (the path ours lacks)."""
    surface, _fr = _factory()
    bad = [n for n in PERPACK if surface.get(("IR", n), ("?",))[0] != "ok"]
    assert not bad, "factory should serve per-pack IR 5000-5126; not ok at: %s" % bad[:20]


# --- the parity scoreboard: ours vs factory, every register ------------------
def test_surface_parity():
    """Diff ours vs the factory across the whole surface and hold it to the
    committed scoreboard (regsweep_expected.py). Structural invariants (per-pack is
    ours-exc/factory-ok; the CAN-seeded BMS telemetry matches) are asserted on any
    image; the exact non-match set is asserted only for the image the scoreboard
    was recorded on (keyed by size), and merely emitted for others."""
    osurf, _ofr = _ours()
    fsurf, _ffr = _factory()
    nonmatch = {k: (osurf.get(k), fsurf.get(k))
                for k in set(osurf) | set(fsurf) if osurf.get(k) != fsurf.get(k)}

    # structural invariant 1: the per-pack block is exactly the ours-exc/factory-ok gap
    for n in PERPACK:
        o, f = osurf.get(("IR", n)), fsurf.get(("IR", n))
        assert o == ("exc", 2) and f[0] == "ok", \
            "per-pack IR %d: ours=%s factory=%s (expected ours-exc/factory-ok)" % (n, o, f)

    # structural invariant 2: the CAN-seeded BMS telemetry agrees (both fed the same
    # 0x355/0x356/0x359 snapshot); the Q1/Q2 misfiling quirks (IR 97/101) are the
    # documented exceptions and are NOT required to match.
    for n in EXP.BMS_MATCH:
        assert osurf.get(("IR", n)) == fsurf.get(("IR", n)), \
            "CAN-seeded IR %d should match: ours=%s factory=%s" \
            % (n, osurf.get(("IR", n)), fsurf.get(("IR", n)))

    # exact scoreboard: only for the recorded image (size-keyed)
    size = os.path.getsize(FACTORY_IMAGE) if os.path.exists(FACTORY_IMAGE) else 0
    if size != EXP.IMAGE_SIZE:
        raise Skip("factory image size %d != recorded %d (%s); scoreboard not pinned "
                   "for this image -- structural invariants still checked"
                   % (size, EXP.IMAGE_SIZE, EXP.IMAGE))
    live = {"%s%d" % k for k in nonmatch}
    assert live == set(EXP.KNOWN_DIFFS), (
        "scoreboard drift vs regsweep_expected.py:\n  new diffs: %s\n  resolved: %s"
        % (sorted(live - set(EXP.KNOWN_DIFFS)), sorted(set(EXP.KNOWN_DIFFS) - live)))


if __name__ == "__main__":
    if "--dump" in sys.argv:
        o, _ = _ours(); f, _ = _factory()
        for k in sorted(set(o) | set(f)):
            if o.get(k) != f.get(k):
                print("%s%-5d ours=%-14s factory=%s" % (k[0], k[1], o.get(k), f.get(k)))
        sys.exit(0)
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (os.path.basename(OURS_BIN) if ours_ok else "(skip)",
                                     os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("whole-surface read sweep + parity scoreboard", label, globals()))
