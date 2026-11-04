#!/usr/bin/env python3
"""
Our-firmware-only tests on the arm_sim harness (tools/arm_sim.py).

These assert the same behavioural contracts as the factory oracle (see
tests/arm_sim_contract.py), but drive our firmware through its *own* named
symbols (src/relay.c, g_ticks) -- so the code here is specific to our build and
cannot be shared with the factory image. The factory side of each contract lives
in tests/test_arm_sim_factory_only.py; both import the same contract tables, so
the two firmwares are held to one identical spec.

Why these are not in the common black-box file: the relays are driven from a
control loop that, in the factory, runs as an RTOS task the harness does not
schedule (docs/19), so they can't be reached purely by injecting a GPIO input.
Instead we call the real drive code with seeded state. g_ticks is an internal
symbol with no factory equivalent.

Usage (same style as test_arm_sim.py -- the image is a command-line argument).
Because these tests call firmware functions *by name*, the symbol table is
needed too, so the .elf is a second argument alongside the flat .bin:

    python3 tests/test_arm_sim_self_only.py build/firmware.bin build/firmware.elf

With no arguments the tests SKIP. Needs `pip install unicorn`; the .elf's symbols
are read with `arm-none-eabi-nm`.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex, load_symbols_nm
from arm_sim_contract import RELAY_OVERRIDE_TRUTH, RUN_STATES, NONRUN_STATES
from arm_sim_runner import Skip, run_tests

# Our firmware under test: (flat .bin, .elf for symbols). Set from argv.
_BIN = [None]
_ELF = [None]


def _ours():
    binp, elfp = _BIN[0], _ELF[0]
    if not binp or not elfp:
        raise Skip("no firmware given (pass build/firmware.bin and "
                   "build/firmware.elf as arguments; run `make` first)")
    for p in (binp, elfp):
        if not os.path.exists(p):
            raise Skip("%s not present (run `make`)" % p)
    if is_intel_hex(binp):
        raise ValueError("%s is an Intel .hex; pass a flat .bin" % binp)
    return ArmSim(binp, load_symbols_nm(elfp))


# --- manual/AutoTest relay override (src/relay.c) ---------------------------
def _relay_override_ours(cmd, manual):
    sim = _ours()
    sim.call("relay_set_override", (cmd, manual))
    sim.clear_drives()
    sim.call("relay_poll")
    return (sim.get_output("PA12"), sim.get_output("PB3"))


def test_relay_override_drives_transfer_pins():
    """Manual/AutoTest relay override (docs/18): in test mode a command word
    drives the AC transfer relays PA12 (bit 1) and PB3 (bit 0); ignored when not
    in manual mode. Our relay_set_override()/relay_poll() must match the shared
    contract (and thus the factory oracle)."""
    for (cmd, manual), exp in RELAY_OVERRIDE_TRUTH.items():
        got = _relay_override_ours(cmd, manual)
        assert got == exp, "ours (cmd=%d manual=%d) = %r, expected %r" % (cmd, manual, got, exp)


# --- working-mode run-enable relay (src/relay.c) ----------------------------
def _run_relay_ours(state):
    sim = _ours()
    sim.call("relay_set_override", (0, 0))
    sim.call("relay_set_mode", (state,))
    sim.clear_drives()
    sim.call("relay_poll")
    return sim.get_output("PC6")


def test_relay_follows_working_mode():
    """The run-enable relay (PC6) is closed when the inverter is in a running
    operating mode (IR_STATE > PROGRAMMING) and open in standby/fault/programming.
    Our relay_set_mode()/relay_poll() must match the shared contract."""
    for st in RUN_STATES:
        assert _run_relay_ours(st) == 1, "ours: PC6 should be closed for state 0x%02x" % st
    for st in NONRUN_STATES:
        assert _run_relay_ours(st) == 0, "ours: PC6 should be open for state 0x%02x" % st


# --- SysTick-driven tick counter (our g_ticks) ------------------------------
def test_systick_advances_tick_counter():
    """The harness has no real timer, so tick-driven firmware logic freezes after
    boot -- unless SysTick injection is on. With it on, our firmware's 1 ms tick
    counter (g_ticks) advances; with it off it stays at 0."""
    off = _ours(); off.run_reset(max_insn=800_000)
    assert off.r32(off.sym("g_ticks")) == 0, "g_ticks advanced without SysTick"
    on = _ours(); on.enable_systick(20_000); on.run_reset(max_insn=800_000)
    assert on.r32(on.sym("g_ticks")) > 0, "SysTick injection did not advance g_ticks"


# --- zero-dependency runner (same invocation style as test_arm_sim.py) ------
def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) >= 1:
        _BIN[0] = args[0]
    if len(args) >= 2:
        _ELF[0] = args[1]
    image = "%s (+%s)" % (_BIN[0], _ELF[0]) if _BIN[0] and _ELF[0] else "<none>"
    return run_tests("Our-firmware-only tests", image, globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
