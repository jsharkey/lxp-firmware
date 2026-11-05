#!/usr/bin/env python3
"""
Common GPIO-behaviour tests on the arm_sim harness (tools/arm_sim.py), run
against ONE firmware image given on the command line.

The whole point of this file: the *exact same* test code runs against both our
open-source build and the factory reference image -- there is no per-image
branching, no symbols, no sniffing which firmware is loaded. Each test boots the
image as a black box, injects a GPIO input and/or reads a GPIO output (or a
memory-mapped peripheral register), and asserts a behaviour that both firmwares
must exhibit. Because the identical spec passes against both images, the factory
oracle and our reimplementation are proven to agree -- parity by shared contract.

The Makefile's `test-sim` target invokes this twice, once per image:

    python3 tests/test_arm_sim.py build/firmware.bin          # our firmware
    python3 tests/test_arm_sim.py reference/com_flat.bin      # factory oracle (flat .bin)

Target-specific tests (which must name internal symbols or addresses, so they
cannot be shared) live in their own files:

    tests/test_arm_sim_self_only.py      -- our firmware, by symbol
    tests/test_arm_sim_factory_only.py   -- the factory image, by address

Usage:
    python3 tests/test_arm_sim.py [IMAGE]

IMAGE must be a flat .bin (an Intel .hex is rejected -- convert it first with
`make factory` or tools/hex2bin.py). If omitted, $LXP_SIM_IMAGE is used, else
build/firmware.bin if it exists (so plain `python3 tests/test_arm_sim.py` and
pytest still work after `make`). Tests SKIP (not fail) when no image is
available. Needs `pip install unicorn`.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_runner import Skip, run_tests

# Image under test. Set by the __main__ runner from argv; otherwise resolved
# from the environment / default build so pytest and a bare run still work.
_IMAGE = [None]


def _resolve_image():
    if _IMAGE[0]:
        return _IMAGE[0]
    env = os.environ.get("LXP_SIM_IMAGE")
    if env:
        return env
    if os.path.exists("build/firmware.bin"):
        return "build/firmware.bin"
    return None


def _sim():
    """Build a fresh sim on the flat-.bin image under test (no symbols -- these
    tests are pure black box, so the same code loads our .bin and the factory
    .bin alike). A .hex is rejected: convert it first (`make factory`)."""
    path = _resolve_image()
    if not path:
        raise Skip("no image (pass one on the command line, set $LXP_SIM_IMAGE, "
                   "or `make` so build/firmware.bin exists)")
    if not os.path.exists(path):
        raise Skip("image %s not found" % path)
    if is_intel_hex(path):
        raise ValueError("%s is an Intel .hex; test_arm_sim.py takes a flat .bin "
                         "only -- convert it first (`make factory` or "
                         "tools/hex2bin.py)" % path)
    return ArmSim(path)


def _observe_pb7():
    """Black box: boot the firmware, hold PB7 at each level, let *its own* event
    loop notice the input and drive the output. Returns {level: PB7 driven high?}.

    No firmware entry point is named -- we only inject a GPIO input, run the loop,
    and read a GPIO output, so the same logic works for any image. (The factory
    image boots its App above an absent bootloader; the harness finds the vector
    table itself.)
    """
    # Warm up ONCE: boot the firmware up to the first time its loop samples PB7
    # (boot is done, and it's reached the same way regardless of PB7's level), then
    # snapshot. Each case restores that identical warm state -- hermetic, but we
    # pay the (slow) boot only once instead of per case.
    sim = _sim()
    sim.run_until_input_read("PB7")
    warm = sim.snapshot()

    out = {}
    for level in (1, 0):
        sim.restore(warm)
        sim.set_input("PB7", level)
        sim.clear_drives()
        # Resume from the warm point; stop at the PB7-high edge if it comes. A
        # small budget comfortably covers the sampler's decision window, so the
        # low case (no edge) also finishes fast.
        out[level] = sim.run_until_output("PB7", level=1, max_insn=200_000,
                                          reset=False)
    return out


def test_pb7_input_drives_output():
    """Holding the PB7 line high makes the firmware's own event loop drive PB7
    high; holding it low does not -- the minimal input->output causality that
    proves the harness instruments real firmware correctly.

    Both firmwares must exhibit this; asserting the same contract against each
    image (run separately) is how factory-vs-ours parity is established, without
    this test ever telling the two apart. (In the ceaa-07xx image this is factory
    sub_0802e452, which debounce-samples PB7 10x and drives it high on a majority;
    our pb7_sample_poll() mirrors it -- but this test invokes neither directly, it
    just runs each firmware's loop as a black box. docs/16: PB7 is the board's
    bit-banged line.)
    """
    got = _observe_pb7()
    assert got == {1: True, 0: False}, "firmware did not propagate PB7: %r" % got


def test_boots_and_configures_usart3_gpio():
    """The firmware boots in the harness and configures GPIOB for USART3 (the
    RS485/dongle Modbus link): PB10 = AF push-pull (0xB), PB11 = floating input
    (0x4). Both firmwares bring USART3 up the same way, so this is a common
    boot/IO smoke test -- proof the harness runs each image through its init, not
    just isolated functions."""
    sim = _sim()
    sim.run_reset(max_insn=300_000)
    crh = sim.r32(0x40010C04)                 # GPIOB->CRH
    pb10 = (crh >> 8) & 0xF                    # PB10 = USART3_TX
    pb11 = (crh >> 12) & 0xF                   # PB11 = USART3_RX
    assert pb10 == 0xB, "PB10 mode nibble = 0x%x (expected 0xB AF-PP 50MHz)" % pb10
    assert pb11 == 0x4, "PB11 mode nibble = 0x%x (expected 0x4 floating input)" % pb11


def test_modbus_charge_current_write_read():
    """Dongle Modbus over USART3 (docs/04): set HR 101 (ChargeCurr) to 42 with a
    0x06 write-single, read it back with a 0x03 read-holding, then overwrite it
    with 43 and confirm the edit reads back. Pure wire-level black box -- frame a
    request on the UART, let the firmware's own loop answer, parse the reply --
    so the same test holds for any image that speaks the EG4 dongle protocol.

    NOTE: this may fail against either image while their dongle-Modbus paths are
    still being built out (e.g. the factory parses RX in the USART3 IRQ, which
    the harness does not yet fire). That is expected for now."""
    from arm_sim_modbus import ModbusDongle
    HR_CHARGE_CURR = 101

    mb = ModbusDongle(_sim())

    assert mb.write_single(HR_CHARGE_CURR, 42) == 42, \
        "0x06 write of ChargeCurr=42 was not acknowledged"
    assert mb.read_holding(HR_CHARGE_CURR) == [42], \
        "0x03 read did not return the written ChargeCurr=42"

    assert mb.write_single(HR_CHARGE_CURR, 43) == 43, \
        "0x06 overwrite of ChargeCurr=43 was not acknowledged"
    assert mb.read_holding(HR_CHARGE_CURR) == [43], \
        "0x03 read did not return the edited ChargeCurr=43"


def test_can_battery_soc_soh_reaches_modbus():
    """Battery BMS CAN (docs/20) -> Modbus. The pack reports SOC/SOH on CAN1 ID
    0x355; the ARM polls CAN1, caches it, and serves it as Modbus input register
    5 (IR_SOC_SOH: low byte SOC %, high byte SOH %). Inject a 0x355 frame on the
    battery bus, then read IR 5 over the dongle and confirm the values crossed
    from CAN to Modbus.

    SCAFFOLDING -- expected to fail for now: our firmware has no CAN reader yet,
    and the factory polls CAN1 from an RTOS task the harness does not schedule.
    The test pins the end-to-end contract (CAN -> register image -> Modbus)."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_can import CanBattery
    IR_SOC_SOH = 5
    SOC, SOH = 77, 96

    sim = _sim()
    battery = CanBattery(sim)     # install CAN1 hooks before the image runs
    mb = ModbusDongle(sim)        # boots the image + installs the UART hooks

    battery.send_soc_soh(SOC, SOH)       # pack announces state of charge/health

    got = mb.read_input(IR_SOC_SOH)
    assert got == [(SOH << 8) | SOC], \
        "CAN SOC=%d/SOH=%d did not reach Modbus IR 5 (got %r)" % (SOC, SOH, got)


# --- zero-dependency runner (so `make test-sim` needs only unicorn) ---------
def _main(argv):
    # Optional single positional arg: the image to test. (argparse would reject
    # pytest's own flags, so keep it this simple.)
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        _IMAGE[0] = args[0]
    return run_tests("Common tests (both images)",
                     _resolve_image() or "<none>", globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
