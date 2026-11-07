#!/usr/bin/env python3
"""USART3 RX demux -- the SAME spec, factory-vs-ours (docs/39 T09).

Proves what the ARM consumes on the USART3 (ARM<->DSP) wire: Modbus requests
(func 03/04/06/10) and DSP bootloader frames (21/22/23) -- and NOT the DSP's
0x49 type-1 telemetry, which is rejected. The factory's real USART3 RX byte
handler and our inv_dsp_rx_classify() must agree on accept/reject for every
vector. See dsprx_contract.py and docs/wiring/ARM-USART3-DSP/telemetry-0x49.md.

Run (from repo root):
    python3 tests/test_dsp_rx.py                            # factory if present
    python3 tests/test_dsp_rx.py FACTORY.bin
    python3 tests/test_dsp_rx.py --ours-bin B --ours-elf E
Or `make test-sim`. (The pure-function host test is tests/test_dsp_rx.c.)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from arm_sim_runner import run_tests, Skip                      # noqa: E402
from dsprx_contract import RX_VECTORS, REJECT, FactoryBackend, OursBackend  # noqa: E402


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


def test_factory_usart3_rx_demux():
    """Factory: the USART3 RX accepts Modbus (03/04/06/10) and bootloader
    (21/22/23) frames and REJECTS a 0x49/type-1 telemetry frame -- so the DSP
    0x49 telemetry is not consumed on this wire."""
    fb = _factory_or_skip()
    fails = []
    for label, first, func, exp in RX_VECTORS:
        got = fb.accepts(first, func)
        want = (exp != REJECT)
        if got != want:
            fails.append("%-28s accepts=%s, expected %s" % (label, got, want))
    assert not fails, "factory\n        " + "\n        ".join(fails)


def test_ours_usart3_rx_demux():
    """Our inv_dsp_rx_classify() reproduces the same accept/reject (and names the
    class) for every vector -- same spec as the factory oracle."""
    ob = _ours_or_skip()
    fails = []
    for label, first, func, exp in RX_VECTORS:
        got = ob.classify(first, func)
        if got != exp:
            fails.append("%-28s class=%d, expected %d" % (label, got, exp))
    assert not fails, "ours\n        " + "\n        ".join(fails)


def test_factory_and_ours_agree():
    """accept/reject parity: the factory's assemble-or-drop matches ours' REJECT
    vs non-REJECT on every vector."""
    fb, ob = _factory_or_skip(), _ours_or_skip()
    fails = []
    for label, first, func, _exp in RX_VECTORS:
        fac_accept = fb.accepts(first, func)
        ours_accept = ob.classify(first, func) != REJECT
        if fac_accept != ours_accept:
            fails.append("%-28s factory=%s ours=%s" % (label, fac_accept, ours_accept))
    assert not fails, "\n        " + "\n        ".join(fails)


if __name__ == "__main__":
    have = os.path.exists(FACTORY_IMAGE)
    ours_ok = bool(OURS_BIN and OURS_ELF and os.path.exists(OURS_BIN or ""))
    label = "ours=%s  factory=%s" % (
        os.path.basename(OURS_BIN) if ours_ok else "(skip)",
        os.path.basename(FACTORY_IMAGE) if have else "(none)")
    sys.exit(run_tests("USART3 RX demux (Modbus/bootloader; 0x49 not telemetry)", label, globals()))
