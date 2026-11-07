#!/usr/bin/env python3
"""Inverter -> battery CAN keep-alive TX capture -- factory-vs-ours (T11b).

Captures the keep-alive each image transmits on CAN1 and checks it against the
factory oracle: 0x305, DLC 8, all-zero payload (see can_tx_contract.py and
docs/wiring/ARM-CAN1-BMS.md). Needs the factory's TX task to run (RTOS, T02).

Run (from repo root):
    python3 tests/test_can_tx.py                              # factory if present
    python3 tests/test_can_tx.py FACTORY.bin                  # name the image
    python3 tests/test_can_tx.py --ours-bin B --ours-elf E    # our firmware build
Or `make test-sim`. Each half SKIPs cleanly when unicorn / a built firmware / the
proprietary factory image is absent. Needs `pip install unicorn`.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from can_tx_contract import INV_ALIVE, FactoryBackend, OursBackend  # noqa: E402


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
        or os.path.join(ROOT, "reference", "com_flat.bin")
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


def _assert_zero_keepalive(frames, who):
    assert frames, "%s transmitted no 0x305 keep-alive" % who
    cid, dlc, data = frames[0]
    assert cid == INV_ALIVE, "%s: id 0x%03x, expected 0x305" % (who, cid)
    assert dlc == 8, "%s: 0x305 DLC %d, expected 8" % (who, dlc)
    assert data == b"\x00" * 8, "%s: 0x305 payload %s, expected all-zero" % (who, data.hex())
    return (dlc, data)


# --- the tests --------------------------------------------------------------
def test_factory_keepalive_is_zero():
    """Oracle: the factory inverter transmits 0x305 DLC 8 all-zero on CAN1 once it
    has seen the pack -- captured black-box off the bxCAN TX mailbox."""
    _assert_zero_keepalive(_factory_or_skip().keepalives(), "factory")


def test_ours_keepalive_is_zero():
    """Our firmware (main.c ~1 Hz keep-alive, can_port.c) transmits the same 0x305
    DLC 8 all-zero frame -- matching the factory, no longer 'provisional'."""
    _assert_zero_keepalive(_ours_or_skip().keepalives(), "ours")


def test_keepalive_agrees():
    """The two images agree byte-for-byte on the keep-alive (id, DLC, payload)."""
    fac = _assert_zero_keepalive(_factory_or_skip().keepalives(), "factory")
    ours = _assert_zero_keepalive(_ours_or_skip().keepalives(), "ours")
    assert fac == ours, "factory %r vs ours %r" % (fac, ours)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("inverter->battery CAN keep-alive TX", label, globals()))
