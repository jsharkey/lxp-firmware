#!/usr/bin/env python3
"""Live USART3 config-push capture -- the SAME spec, factory-vs-ours.

Writes a holding register over the Modbus dongle, then serializes the config
snapshot with the image's OWN block builder and checks which config-frame byte
moved (differential A-vs-B). Proves where the HR 64-89 charge/discharge schedule
registers actually land on the ARM->DSP link -- see dsppush_contract.py and
docs/wiring/ARM-USART3-DSP/field-provenance.md.

  * ours    -- our dsp_build_config_frame(&g_dsp_src, ...) by symbol (src/dsp/)
  * factory -- the real per-block filler sub_08024dfc by address

Run (from repo root):
    python3 tests/test_dsp_push.py                              # factory if present
    python3 tests/test_dsp_push.py FACTORY.bin                  # name the image
    python3 tests/test_dsp_push.py --ours-bin B --ours-elf E    # our firmware build
Or `make test-sim`. Each half SKIPs cleanly when unicorn / a built firmware /
the proprietary factory image is absent. Needs `pip install unicorn`.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from dsppush_contract import (DSP_PUSH, WRITABLE_64_89, INERT_64_89,
                              ab_values, CALIB_BLOCKS, EXPECT_CAL, calib_payloads,
                              GRID_PUSH, GRID_AB, ABS_WRITES_BY_BLOCK, ABS_OFFSETS,
                              FactoryBackend, OursBackend)  # noqa: E402


def _parse(argv):
    image = ours_bin = ours_elf = None
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
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
        or os.path.join(ROOT, "reference", "ceaa-07xx_vE_260214.bin")
    return image, ours_bin, ours_elf


FACTORY_IMAGE, OURS_BIN, OURS_ELF = _parse(sys.argv[1:])
_fac_cache, _ours_cache = [], []


def _factory_or_skip():
    if not _fac_cache:
        _fac_cache.append(FactoryBackend(FACTORY_IMAGE))
    fb = _fac_cache[0]
    if not fb.available():
        raise Skip("needs unicorn + factory image (%s)" % FACTORY_IMAGE)
    return fb


def _ours_or_skip():
    if not _ours_cache:
        _ours_cache.append(OursBackend(OURS_BIN, OURS_ELF))
    ob = _ours_cache[0]
    if not ob.available():
        raise Skip("needs unicorn + a built firmware (pass --ours-bin/--ours-elf; run `make`)")
    return ob


# The window TIMES occupy payload offsets 0x17..0x22 (three big-endian u16 pairs).
# The slot-enable / dirty mask word (payload 0x15..0x16, -> DSP 0xAD54) also moves
# when a schedule edit dirties its slot -- that is the slot-committer design working
# (docs/wiring/ARM-USART3-DSP), not a window byte -- so the spec is asserted over the window
# region only. (The factory also mirrors that mask into block 0 @0x25 and blocks
# 3/6 @0x15; all outside this window, so excluded uniformly for both images.)
WIN_LO, WIN_HI = 0x17, 0x23


def _expected_delta(reg):
    """The set of (block, offset) window-region bytes the spec says `reg` moves."""
    spec = DSP_PUSH[reg]
    if spec is None:
        return set()
    blk, off = spec
    return {(blk, off), (blk, off + 1)}      # big-endian u16 = two bytes


def _windows_only(delta):
    return {(b, k) for (b, k) in delta if WIN_LO <= k < WIN_HI}


def _check_push_matches_spec(backend):
    fails = []
    for reg in sorted(DSP_PUSH, key=lambda r: (DSP_PUSH[r] is None, r)):
        a, b = ab_values(reg)
        got = _windows_only(backend.push_delta(reg, a, b))
        exp = _expected_delta(reg)
        if got != exp:
            where = DSP_PUSH[reg]
            fails.append("HR %-3d expected %s, got %s"
                         % (reg, ("block %d @0x%02x" % where) if where else "not pushed",
                            sorted(got)))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


# --- the tests --------------------------------------------------------------
def test_factory_push_matches_spec():
    """Factory: dongle write -> real block builder -> the frame byte the shared
    DSP_PUSH spec predicts (AC-charge windows->block4, AC-First->block5, BE16;
    AC-charge power not pushed)."""
    _check_push_matches_spec(_factory_or_skip())


def test_ours_push_matches_spec():
    """Our firmware must push the same registers to the same block/offset (and
    must NOT push the ones the factory doesn't) -- same spec as the oracle."""
    _check_push_matches_spec(_ours_or_skip())


def test_factory_schedule_writability():
    """Ground truth for the HR 64-89 block in the factory image: 64/65/66/68-73
    are live (a dongle write reads back); 67 (AC-charge SOC) and 74-89
    (charge-priority + forced-discharge) are inert -- not writable, hence nothing
    to push. Documents why those registers can't be exercised by capture."""
    fb = _factory_or_skip()
    bad = []
    for reg in sorted(WRITABLE_64_89):
        a, _ = ab_values(reg)
        if not fb.writable(reg, a):
            bad.append("HR %d should be writable but did not store" % reg)
    for reg in sorted(INERT_64_89):
        a, _ = ab_values(reg)
        if fb.writable(reg, a):
            bad.append("HR %d should be inert but stored a write" % reg)
    assert not bad, "factory\n        " + "\n        ".join(bad)


def test_factory_calibration_gains_unity():
    """Factory: the calibration-gain blocks (2/7/8) are Q10 unity-gain (0x0400)
    tables -- the uncalibrated default, fed by no holding register (block-02/07/08
    + field-provenance). This is the byte spec our firmware reproduces."""
    fb = _factory_or_skip()
    got = calib_payloads(fb)
    fails = []
    for blk in CALIB_BLOCKS:
        if got[blk] != EXPECT_CAL[blk]:
            fails.append("block %d\n          got :%s\n          want:%s"
                         % (blk, got[blk].hex(" "), EXPECT_CAL[blk].hex(" ")))
    assert not fails, "factory\n        " + "\n        ".join(fails)


def test_ours_calibration_gains_match_factory():
    """Our blocks 2/7/8 payloads are byte-identical to the factory's -- same unity
    calibration defaults (T10). Independent of settings/BMS, so one build suffices."""
    fb, ob = _factory_or_skip(), _ours_or_skip()
    fp, op = calib_payloads(fb), calib_payloads(ob)
    fails = []
    for blk in CALIB_BLOCKS:
        if fp[blk] != op[blk]:
            fails.append("block %d\n          FAC :%s\n          OURS:%s"
                         % (blk, fp[blk].hex(" "), op[blk].hex(" ")))
    assert not fails, "\n        " + "\n        ".join(fails)


def test_push_tracks_changes_over_time():
    """A changed schedule value is re-serialized (full snapshot, not a one-shot):
    editing a window register to a different time moves its frame byte, so the DSP
    sees live edits -- the differential capture is itself the proof. Factory side."""
    fb = _factory_or_skip()
    a, b = (8 << 8) | 6, (12 << 8) | 0      # 06:08 -> 00:12
    seen = _windows_only(fb.push_delta(68, a, b))
    assert (4, 0x17) in seen and (4, 0x18) in seen, \
        "HR 68 edit %04x->%04x did not reach block 4 @0x17 (saw %s)" % (a, b, sorted(seen))


# --- grid-charge slot scalar fields (blocks 3 & 6) --------------------------
def _check_grid_matches_spec(backend):
    """Each GRID_PUSH register, when its dongle value changes, must move exactly
    the field bytes the spec names in its target block -- and no other byte in that
    block at offset >= 0x17 (the payload 0x15/0x16 mask + block-0 residue are shared
    modbus-buffer noise, excluded by restricting to the target block at 0x17+)."""
    fails = []
    for reg in sorted(GRID_PUSH):
        blk, off, width = GRID_PUSH[reg]
        a, b = GRID_AB[reg]
        delta = backend.push_delta(reg, a, b)
        # target block, payload >= 0x17; drop the block-0 modbus-RX residue at
        # 0x25/0x26 (shared buffer bleed, not a field -- see dsppush_contract).
        got = {(bb, oo) for (bb, oo) in delta
               if bb == blk and oo >= 0x17 and not (bb == 0 and oo in (0x25, 0x26))}
        exp = {(blk, off + i) for i in range(width)}
        if got != exp:
            fails.append("HR %-3d expected block %d @0x%02x (%dB), got %s"
                         % (reg, blk, off, width, sorted(got)))
    assert not fails, "%s\n        " % backend.name + "\n        ".join(fails)


def test_factory_grid_push_matches_spec():
    """Factory: dongle write -> real block builder packs the grid-charge slot
    scalars (charge/discharge current + charge voltage -> block 6; EOD + feed-in
    limit -> block 3) at the GRID_PUSH offsets. docs/wiring/ARM-USART3-DSP."""
    _check_grid_matches_spec(_factory_or_skip())


def test_ours_grid_push_matches_spec():
    """Our firmware packs the same grid-charge scalars to the same block/offset,
    with the DSP unit scaling (currents A->0.1A), so ours is byte-faithful to the
    factory for these fields (T10)."""
    _check_grid_matches_spec(_ours_or_skip())


def test_ours_matches_factory_absolute():
    """Strongest check: per block, drive factory AND ours to the identical register
    state (ABS_WRITES_BY_BLOCK) on FRESH backends, then every HR-driven payload byte
    (ABS_OFFSETS) must be byte-for-byte equal. Unlike the differential specs this pins
    the VALUE, so a wrong scale/packing/lookup in ours is caught independently of the
    decode. Fresh per-block backends keep each write set within the factory's dongle
    transaction budget and avoid polluting the shared cached backends."""
    _factory_or_skip(); _ours_or_skip()      # skip early if unavailable
    fails = []
    for blk, writes in sorted(ABS_WRITES_BY_BLOCK.items()):
        fb = FactoryBackend(FACTORY_IMAGE)
        ob = OursBackend(OURS_BIN, OURS_ELF)
        ff = fb.blocks_after_writes(writes)[blk]
        of = ob.blocks_after_writes(writes)[blk]
        for o in ABS_OFFSETS[blk]:
            if ff[o] != of[o]:
                fails.append("block %d @0x%02x: factory=0x%02x ours=0x%02x"
                             % (blk, o, ff[o], of[o]))
    assert not fails, "\n        " + "\n        ".join(fails)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("ARM->DSP config-push live capture", label, globals()))
