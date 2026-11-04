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


def _observe_pb7(make_sim):
    """Black box: boot the firmware, hold PB7 at each level, let *its own* event
    loop notice the input and drive the output. Returns {level: PB7 driven high?}.

    No firmware entry point is named — we only inject a GPIO input, run the loop,
    and read a GPIO output, so the same logic works for the factory image and
    for our firmware. (The factory image boots its App above an absent
    bootloader; the harness finds the vector table itself.)
    """
    out = {}
    for level in (1, 0):
        sim = make_sim()
        sim.set_input("PB7", level)
        sim.clear_drives()
        # Run the loop and stop the moment PB7 is driven high (the expected edge);
        # for the low case, stop once the loop has sampled PB7 ~40 times without
        # driving it. Either way we finish fast instead of burning a huge budget.
        out[level] = sim.run_until_output("PB7", level=1,
                                          settle_input="PB7", settle_reads=40)
    return out


def test_pb7_input_drives_output():
    """Holding the PB7 line high makes the firmware's own event loop drive PB7
    high; holding it low does not. Our firmware must do this, and must match the
    factory image (the oracle) when it is available.

    (Factory sub_0802e452 debounce-samples PB7 and drives it high on a majority;
    our pb7_sample_poll() mirrors that — but this test invokes neither directly,
    it just runs each firmware's loop as a black box. docs/16: PB7 is the
    board's bit-banged line.)
    """
    ours = _observe_pb7(_ours)
    assert ours == {1: True, 0: False}, "our firmware did not propagate PB7: %r" % ours

    try:
        factory = _observe_pb7(_factory)
    except Skip:
        return   # no factory image: our-firmware behaviour was still verified
    assert factory == ours, "factory %r != ours %r" % (factory, ours)


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
