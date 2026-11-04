#!/usr/bin/env python3
"""
GPIO-behaviour tests on the arm_sim harness (tools/arm_sim.py).

Two things are proven here, end-to-end:

  1. BASE CASE (factory image = oracle): the function sub_0802e452 in the
     ceaa-07xx image debounce-samples PB7 as an INPUT (10x via
     GPIO_ReadInputDataBit) and, iff the majority read high, drives PB7 HIGH via
     GPIO_SetBits and sets status flag 0x2000d890 bit 6. So flipping one GPIO
     INPUT flips a GPIO OUTPUT — the minimal input->output causality that proves
     the harness instruments real firmware correctly.

  2. OUR FIRMWARE runs in the same harness: booting build/firmware.bin from its
     reset vector reaches mb_port_init, which configures GPIOB->CRH for USART3
     (PB10 = AF push-pull, PB11 = floating input). This is the hook future
     feature tests grow from: assert our firmware's GPIO behaviour the same way.

Runs with plain `python3 tests/test_arm_sim.py` (only needs `pip install
unicorn`); also discoverable by pytest if installed. Tests that need an image
SKIP (not fail) when it is absent, since the factory image is never committed.

Factory image location: $LXP_FACTORY_BIN or reference/com_flat.bin.
Our firmware:           build/firmware.bin (+ .elf) — run `make` first.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from arm_sim import ArmSim

FACTORY_HEX = os.environ.get("LXP_FACTORY_HEX")                      # vendor .hex (converted in-memory)
FACTORY_BIN = os.environ.get("LXP_FACTORY_BIN", "reference/com_flat.bin")  # pre-converted flat image

class Skip(Exception):
    pass


def _factory():
    # symbols optional (we call by address). Either env var accepts either an
    # Intel HEX or a raw flat .bin -- the format is auto-detected by content.
    path = FACTORY_HEX or (FACTORY_BIN if os.path.exists(FACTORY_BIN) else None)
    if not path:
        raise Skip("no factory image (set $LXP_FACTORY_HEX to a vendor .hex, "
                   "or $LXP_FACTORY_BIN / reference/com_flat.bin to a flat image)")
    if not os.path.exists(path):
        raise Skip("factory image %s not found" % path)
    return ArmSim.from_image(path)

def _ours():
    if not (os.path.exists("build/firmware.bin") and os.path.exists("build/firmware.elf")):
        raise Skip("build/firmware.{bin,elf} not present (run `make`)")
    return ArmSim.ours()


# --------------------------------------------------------------------------
# Parity behaviours: a GPIO contract each implementation must satisfy, stated
# as observable input->output. The SAME contract is asserted against the
# factory image (the oracle) and against our firmware, so new behaviours are
# added by appending to BEHAVIOURS, not by writing per-image tests.
#
# Each behaviour:
#   name        - label
#   in_pin      - the GPIO input it reacts to (docs/16 name)
#   out_pin     - the GPIO output it drives
#   factory     - how to invoke it on the factory image (address or symbol)
#   ours        - how to invoke it in our firmware (symbol)
#   expected    - {input_level: output_driven_high?} the contract
# --------------------------------------------------------------------------
BEHAVIOURS = [
    dict(
        # Factory sub_0802e452 debounce-samples PB7 (10x) and, on majority-high,
        # drives PB7 high (sets a status flag too, but the observable contract is
        # the GPIO drive). docs/16 PB7 = the bit-banged line; docs/18 context.
        name="pb7_input_drives_output",
        in_pin="PB7", out_pin="PB7",
        factory=0x0802e452,          # ceaa-07xx d673c5ed-...-260214
        ours="pb7_sample_poll",
        expected={1: True, 0: False},
    ),
]

def _observe(make_sim, in_pin, out_pin, entry, levels):
    """Run `entry` for each input level on a fresh sim; return {level: driven-high}."""
    obs = {}
    for lvl in levels:
        sim = make_sim()
        sim.set_input(in_pin, lvl)
        sim.clear_drives()
        sim.call(entry)
        obs[lvl] = sim.was_driven(out_pin, level=1)
    return obs

def test_behaviours_ours():
    """Our firmware satisfies each GPIO behaviour contract."""
    for b in BEHAVIOURS:
        obs = _observe(_ours, b["in_pin"], b["out_pin"], b["ours"], b["expected"].keys())
        assert obs == b["expected"], "%s: ours=%r expected=%r" % (b["name"], obs, b["expected"])

def test_behaviours_factory_vs_ours_parity():
    """Factory image and our firmware drive the output identically (the goal)."""
    for b in BEHAVIOURS:
        fac = _observe(_factory, b["in_pin"], b["out_pin"], b["factory"], b["expected"].keys())
        our = _observe(_ours,    b["in_pin"], b["out_pin"], b["ours"],    b["expected"].keys())
        assert fac == our == b["expected"], \
            "%s: factory=%r ours=%r expected=%r" % (b["name"], fac, our, b["expected"])


def test_our_firmware_boots_and_configures_usart3_gpio():
    """Our firmware boots in the harness and mb_port_init configures GPIOB."""
    sim = _ours()
    sim.run_reset(max_insn=300_000)
    crh = sim.r32(0x40010C04)                # GPIOB->CRH
    pb10 = (crh >> 8) & 0xF                   # PB10 = USART3_TX
    pb11 = (crh >> 12) & 0xF                  # PB11 = USART3_RX
    assert pb10 == 0xB, "PB10 mode nibble = 0x%x (expected 0xB AF-PP 50MHz)" % pb10
    assert pb11 == 0x4, "PB11 mode nibble = 0x%x (expected 0x4 floating input)" % pb11


# --- zero-dependency runner (so `make test-sim` needs only unicorn) ---------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    rc = 0
    for t in tests:
        try:
            t(); print("PASS  %s" % t.__name__)
        except Skip as s:
            print("SKIP  %s  (%s)" % (t.__name__, s))
        except AssertionError as a:
            rc = 1; print("FAIL  %s\n        %s" % (t.__name__, a))
        except Exception as e:
            rc = 1; print("ERROR %s\n        %r" % (t.__name__, e))
    sys.exit(rc)
