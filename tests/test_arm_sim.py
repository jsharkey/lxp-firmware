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

# --- facts about the ceaa-07xx factory image (d673c5ed-ceaa-07xx_vE_260214) ---
PB7_SAMPLER_FN = 0x0802e452   # samples PB7 input, drives PB7 + flag on majority-high
PB7_FLAG_ADDR  = 0x2000d890   # status word; bit 6 set when PB7 sampled high
PB7_FLAG_BIT   = 6

class Skip(Exception):
    pass


def _factory():
    # symbols optional (we call by address). Prefer a vendor .hex if given.
    if FACTORY_HEX:
        if not os.path.exists(FACTORY_HEX):
            raise Skip("LXP_FACTORY_HEX=%s not found" % FACTORY_HEX)
        return ArmSim.from_hex(FACTORY_HEX)
    if not os.path.exists(FACTORY_BIN):
        raise Skip("no factory image (set $LXP_FACTORY_HEX to a vendor .hex, "
                   "or $LXP_FACTORY_BIN / reference/com_flat.bin to a flat image)")
    return ArmSim(FACTORY_BIN)

def _ours():
    if not (os.path.exists("build/firmware.bin") and os.path.exists("build/firmware.elf")):
        raise Skip("build/firmware.{bin,elf} not present (run `make`)")
    return ArmSim.ours()


def test_factory_pb7_input_drives_output():
    """A GPIO input change (PB7) causes a GPIO output change (PB7 driven) + flag."""
    for level in (1, 0):
        sim = _factory()
        sim.w32(PB7_FLAG_ADDR, 0)            # clean slate
        sim.set_input("PB7", level)
        sim.clear_drives()
        sim.call(PB7_SAMPLER_FN)
        drove_high = sim.was_driven("PB7", level=1)
        flag = sim.bit(PB7_FLAG_ADDR, PB7_FLAG_BIT)
        assert drove_high == bool(level), \
            "PB7 input=%d: expected drive-high=%s, got %s" % (level, bool(level), drove_high)
        assert sim.get_output("PB7") == level, \
            "PB7 input=%d: output latch = %d" % (level, sim.get_output("PB7"))
        assert flag == level, \
            "PB7 input=%d: flag bit6 = %d" % (level, flag)


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
