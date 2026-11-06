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
from arm_sim_contract import (RELAY_OVERRIDE_TRUTH, RUN_STATES, NONRUN_STATES,
                              SAFETY_TELEMETRY, SAFETY_TELEMETRY_A, SAFETY_TELEMETRY_B,
                              RTC_WALK, check_live_clock)
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


# --- safety-CPU telemetry -> Modbus input registers (docs/30, docs/33) ------
# Our side of the shared telemetry contract. The fake safety CPU writes the
# decoded fields into our telemetry bank (g_safety_bank, by symbol); our loop's
# safety_cpu_publish() must copy them into the input-register image with the EG4
# scaling, so the dongle reads them back with the right register + scale and
# tracks changes over time. The factory oracle side is in
# test_arm_sim_factory_only.py; both assert SAFETY_TELEMETRY.
def _safety_ours():
    from arm_sim_modbus import ModbusDongle
    from arm_sim_safety import FakeSafetyCpu
    sim = _ours()
    bank = sim.sym("g_safety_bank")
    return FakeSafetyCpu(sim, bank, ModbusDongle(sim))


def test_safety_cpu_telemetry_reaches_modbus():
    """Safety-CPU telemetry (grid/PV/bus V, frequency, radiator temps, inverter
    current) must reach the dongle's Modbus input registers with the right
    register and scaling, and must TRACK CHANGES over time (a second, fluctuated
    snapshot reads back its new values). Our safety_cpu_publish() must match the
    shared contract (and thus the factory oracle)."""
    fake = _safety_ours()
    for label, snapshot in (("A", SAFETY_TELEMETRY_A), ("B", SAFETY_TELEMETRY_B)):
        fake.send(snapshot)
        for name, raw in snapshot.items():
            _off, ir, _sc = SAFETY_TELEMETRY[name]
            exp = fake.expected(name, raw)
            got = fake.served(name)
            assert got == exp, ("ours snapshot %s: %s -> IR %d = %r, expected "
                                "%r (raw %d)" % (label, name, ir, got, exp, raw))


# --- RTC wall-clock calendar walk (src/rtc/rtc.c, docs/36) ------------------
# Our calendar g_rtc and its 1 s advance rtc_tick() are driven by symbol through
# the simulator's RTC control -- the SAME RTC_WALK vectors the factory oracle is
# held to in test_arm_sim_factory_only.py.
def test_rtc_calendar_walks_forward():
    """Walk our RTC forward across second/minute/hour/day/month/year and leap
    boundaries (the shared RTC_WALK contract) and confirm the calendar carries
    correctly. Same spec as the factory oracle."""
    sim = _ours()
    sim.configure_rtc(sim.sym("g_rtc"), "rtc_tick", prescale=None, calls_per_sec=1)
    for label, start, secs, exp in RTC_WALK:
        sim.set_rtc(*start)
        sim.advance_rtc(secs)
        got = sim.get_rtc()
        assert got == exp, ("ours RTC walk %s: from %r +%ds = %r, expected %r"
                            % (label, start, secs, got, exp))


def test_rtc_is_live_clock():
    """Drive our RTC forward and confirm a dongle read reflects it: our Modbus
    time registers are a LIVE read of g_rtc, not an echo of the last write (the
    shared check_live_clock contract; src/rtc/rtc.c + mb_rd_hold)."""
    sim = _ours()
    sim.configure_rtc(sim.sym("g_rtc"), "rtc_tick", None, calls_per_sec=1)
    check_live_clock(sim)


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
