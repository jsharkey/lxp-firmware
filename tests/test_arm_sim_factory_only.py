#!/usr/bin/env python3
"""
Factory-image-only tests on the arm_sim harness (tools/arm_sim.py).

These assert the same behavioural contracts as our firmware (see
tests/arm_sim_contract.py), but invoke the factory ceaa-07xx image's *actual*
relay-drive code by hard-coded address, with seeded state -- so the code here is
specific to the factory image and cannot be shared. Our side of each contract
lives in tests/test_arm_sim_self_only.py; both import the same contract tables,
so the factory oracle and our reimplementation are held to one identical spec.

Why these are not in the common black-box file: the relays are driven from the
factory's main control loop, which runs as an RTOS task the harness does not
schedule (docs/19), so they can't be reached purely by injecting a GPIO input.
Instead we call the genuine factory drive code directly with the state the RTOS
task would act on (the override path is self-contained -- no boot needed).

Usage (same style as test_arm_sim.py -- the image is a command-line argument, a
flat .bin; a .hex is rejected, convert it first with `make factory`):

    python3 tests/test_arm_sim_factory_only.py reference/com_flat.bin

The factory image is never committed (it is proprietary); with no image argument
the tests SKIP. Needs `pip install unicorn`.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_contract import RELAY_OVERRIDE_TRUTH, RUN_STATES, NONRUN_STATES

# Factory flat-.bin image under test. Set by the __main__ runner from argv.
_IMAGE = [None]


class Skip(Exception):
    pass


def _factory():
    path = _IMAGE[0]
    if not path:
        raise Skip("no factory image given (pass a flat .bin as the argument)")
    if not os.path.exists(path):
        raise Skip("factory image %s not found" % path)
    if is_intel_hex(path):
        raise ValueError("%s is an Intel .hex; pass a flat .bin -- convert it "
                         "first (`make factory` or tools/hex2bin.py)" % path)
    return ArmSim(path)


# --- factory internals for the manual/AutoTest relay override (ceaa-07xx) ---
# docs/18: the grid-protection self-test drives the AC transfer relays directly.
# sub_08018a7c, in manual mode, sets PA12 <- cmd bit1 and PB3 <- cmd bit0.
FAC_RELAY_UPDATER = 0x08018a7c
FAC_MANUAL_FLAG   = 0x2000d0e4 + 0xa9   # 1 = manual/test mode
FAC_RELAY_CMD     = 0x2000da6c          # override command word


def _relay_override_factory(cmd, manual):
    sim = _factory()
    sim.wbytes(FAC_MANUAL_FLAG, bytes([manual]))
    sim.wbytes(FAC_RELAY_CMD, bytes([cmd & 0xFF, (cmd >> 8) & 0xFF]))
    sim.clear_drives()
    sim.call(FAC_RELAY_UPDATER)
    return (sim.get_output("PA12"), sim.get_output("PB3"))


def test_relay_override_drives_transfer_pins():
    """Manual/AutoTest relay override (docs/18), run against the factory's real
    relay-drive code (sub_08018a7c): a command word drives PA12 (bit 1) and PB3
    (bit 0) in manual mode, and is ignored otherwise. The factory image is the
    oracle for the shared override contract."""
    for (cmd, manual), exp in RELAY_OVERRIDE_TRUTH.items():
        got = _relay_override_factory(cmd, manual)
        assert got == exp, "factory (cmd=%d manual=%d) = %r, expected %r" % (cmd, manual, got, exp)


# --- working-mode relay: the run-enable relay PC6 follows IR_STATE ----------
FAC_RUN_RELAY_UPDATER = 0x08016ec6         # PB2/PC6 updater (docs/18)
FAC_IR_STATE          = 0x2000d0e4 + 0xa0  # operating mode byte (= IR_STATE)


def _run_relay_factory(state):
    sim = _factory()
    sim.wbytes(FAC_RELAY_CMD, b"\x00\x00")          # override off
    sim.wbytes(FAC_IR_STATE, bytes([state]))
    sim.clear_drives()
    for _ in range(600):                            # settle the updater's debounce
        sim.call(FAC_RUN_RELAY_UPDATER)
    return sim.get_output("PC6")


def test_relay_follows_working_mode():
    """The run-enable relay (PC6) is closed when the inverter is in a running
    operating mode (IR_STATE > PROGRAMMING) and open in standby/fault/programming
    -- the factory's sub_08016ec6 gate (docs/18). The factory image is the oracle
    for the shared working-mode contract."""
    for st in RUN_STATES:
        assert _run_relay_factory(st) == 1, "factory: PC6 should be closed for state 0x%02x" % st
    for st in NONRUN_STATES:
        assert _run_relay_factory(st) == 0, "factory: PC6 should be open for state 0x%02x" % st


# --- zero-dependency runner (same invocation style as test_arm_sim.py) ------
def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        _IMAGE[0] = args[0]
    print("# test_arm_sim_factory_only.py: image = %s" % (_IMAGE[0] or "<none>"))

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
    return rc


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
