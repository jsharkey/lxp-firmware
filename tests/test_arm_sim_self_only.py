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
                              RTC_WALK, check_live_clock,
                              assert_requests_bootloader)
from arm_sim_runner import Skip, run_tests

# EG4 Modbus (include/inv/modbus_map.h): ResetSetting reg + InvReboot bit.
HR_RESET_SETTING = 11
INV_RESETSETTING_INV_REBOOT = 1 << 7

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


def _run_transfer_ours(enabled, force, grid):
    sim = _ours()
    sim.call("relay_set_override", (0, 0))        # not manual
    sim.call("relay_set_mode", (0,))              # standby (PC6 path irrelevant here)
    sim.call("relay_set_transfer_inputs", (1 if enabled else 0, 1 if force else 0, grid))
    sim.clear_drives()
    sim.call("relay_poll")
    return (sim.get_output("PA12"), sim.get_output("PB3"))


def test_ac_transfer_relays_driven_live():
    """The AC-transfer pair (PA12/PB3) is driven live by relay_poll() from the
    transfer inputs (T14 wiring): disabled -> both open; enabled + grid qualified
    -> PA12 open / PB3 closed; enabled + grid not qualified -> both closed; and the
    DSP force bit -> both closed regardless of grid. Matches inv_ac_transfer_decide()
    and the factory oracle (tests/test_ac_transfer.py)."""
    B20 = 1 << 20
    assert _run_transfer_ours(False, False, 0)       == (0, 0), "disabled -> both open"
    assert _run_transfer_ours(True,  False, B20)     == (0, 1), "enabled grid-ok -> PA12=0 PB3=1"
    assert _run_transfer_ours(True,  False, 0)       == (1, 1), "enabled no-grid -> PA12=1 PB3=1"
    assert _run_transfer_ours(True,  False, B20 | (2 << 29)) == (1, 1), "enabled grid-bad -> 1/1"
    assert _run_transfer_ours(False, True,  B20)     == (1, 1), "DSP force -> both closed (overrides grid)"


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
    from arm_sim_modbus import ModbusDongle
    sim = _ours()
    sim.configure_rtc(sim.sym("g_rtc"), "rtc_tick", None, calls_per_sec=1)
    check_live_clock(sim, ModbusDongle)      # ours serves the dongle on UART5


# --- RS-485 driver-enable around the dongle TX (T01, UART5 on PA15) ---------
def test_modbus_de_toggles_around_tx():
    """On a dongle Modbus transaction our UART5 slave asserts the RS-485
    driver-enable (PA15 high) to drive the bus, then releases it (low) once the
    reply has fully left the shift register (TC) -- so the half-duplex bus is
    handed back to receive. Proves uart5_set_de() sequences DE around TX
    (src/uart/uart5.c; docs/wiring/ARM-UART5-dongle). Ours-specific: PA15 is our
    DE pin; the factory's UART5 DE is not exercised in this harness (its UART5
    path is a non-NVIC task, T02)."""
    from arm_sim_modbus import ModbusDongle
    sim = _ours()
    mb = ModbusDongle(sim)
    sim.clear_drives()                        # ignore boot-time / init DE drives
    assert mb.write_single(101, 42) == 42, "UART5 Modbus write was not acknowledged"
    # The dongle halts on the reply's last byte -- before the TC handler releases
    # the line. Run a little more so the final transmit completes (TC) and DE drops.
    for _ in range(5):
        sim.pend_irq(16 + 53)                 # UART5 IRQ -> ISR runs its TC branch
        sim.run(100_000)
    de = [d for (p, i, d) in sim.drive_log if (p, i) == ("A", 15)]   # PA15 = DE
    assert "HIGH" in de, "DE (PA15) was never asserted for the reply TX: %r" % de
    assert de[-1] == "LOW", "DE (PA15) left asserted after TX (not released on TC): %r" % de
    assert de.index("HIGH") < (len(de) - 1 - de[::-1].index("LOW")), \
        "DE did not go HIGH-before-LOW around a transmit: %r" % de


def test_comaddr_changes_slave_address_live():
    """Writing HR 15 (ComAddr) changes our Modbus slave address **immediately**:
    after a write of 7 (sent to the default address 1) the slave answers on
    address 7 and no longer on 1 -- no reboot required (src/main.c, T12).
    docs/wiring/ARM-UART5-dongle/HR015-ComAddr.md."""
    from arm_sim_modbus import ModbusDongle
    HR_COM_ADDR = 15
    sim = _ours()
    mb = ModbusDongle(sim)                         # boots; default request address 1
    assert mb.write_single(HR_COM_ADDR, 7) == 7, "HR 15 write not acknowledged on addr 1"
    mb.addr = 7                                     # now address the slave as 7
    assert mb.read_holding(HR_COM_ADDR) == [7], "slave did not answer on the NEW address 7"
    mb.addr = 1                                     # the old address must go silent
    assert mb.read_holding(HR_COM_ADDR) is None, "slave still answers on the OLD address 1"


def test_hr11_resetsetting_is_one_shot_command():
    """HR 11 (ResetSetting) is a command, not a stored value: a write triggers the
    action and the register reads back 0 (src/main.c + src/state/command.c, T12).
    We use bit 0 (EnergyRecordClr) -- harmless -- and never bit 7 (reboot)."""
    from arm_sim_modbus import ModbusDongle
    HR_RESET_SETTING = 11
    sim = _ours()
    mb = ModbusDongle(sim)
    assert mb.write_single(HR_RESET_SETTING, 0x01) == 0x01, "HR 11 write not acknowledged"
    assert mb.read_holding(HR_RESET_SETTING) == [0], "HR 11 did not read back 0 (should be one-shot)"


def test_usart2_mode_classified_passthrough_e2e():
    """End-to-end on ours: a USART2 safety frame's mode byte is served at IR 0
    verbatim (pure pass-through, no canonicalisation) and a relayed fault composes
    into the FaultCode (IR 60/61) WITHOUT changing IR 0 -- the classifier contract
    pinned against the 07 factory (docs/39 T06b). Fed on the real USART2 RX wire
    (T05) and read over the dongle; mirrors the factory oracle
    test_usart2_classifier_is_pure_passthrough."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    IR_STATE, IR_FAULT_L, IR_FAULT_H = 0, 60, 61
    sim = _ours()
    mb = ModbusDongle(sim)
    wire = Usart2SafetyWire(sim, boot=False)
    # Non-canonical mode 0x55 + a relayed fault bit 22 (0x00400000).
    wire.feed(build_frame({0x04: (0x55, 1), 0x0d: (0x55, 1), 0x05: (0x00400000, 4)}))
    st = mb.read_input(IR_STATE)
    assert st == [0x55], "non-canonical mode 0x55 not passed through to IR 0 (got %r)" % st
    lo = mb.read_input(IR_FAULT_L); hi = mb.read_input(IR_FAULT_H)
    assert lo and hi, "FaultCode not served (%r / %r)" % (lo, hi)
    fault = lo[0] | (hi[0] << 16)
    assert (fault & 0x00400000) != 0, "relayed fault bit did not reach FaultCode (0x%x)" % fault
    # IR 0 unchanged by the fault.
    assert mb.read_input(IR_STATE) == [0x55], "fault changed IR 0 (should stay the mode byte)"


def test_safety_link_loss_raises_e017():
    """Safety-link (USART2) comms-loss supervision (docs/39 T08): once a CRC-valid
    frame has been seen, E017 (FaultCode bit 17, the ARM-local peer-comms-loss bit,
    docs/29/30) is raised if no further frame arrives within the timeout, and clears
    on the next good frame. Driven on the real USART2 RX wire (T05); the clock is
    advanced by poking g_ticks. The exact factory threshold is sim-blocked (its
    USART2 frame-health task is unscheduled), so ours uses a conservative default."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    IR_FAULT_L, IR_FAULT_H, E017 = 60, 61, 1 << 17
    sim = _ours()
    mb = ModbusDongle(sim)
    wire = Usart2SafetyWire(sim, boot=False)

    def fault_word():
        lo = mb.read_input(IR_FAULT_L); hi = mb.read_input(IR_FAULT_H)
        assert lo and hi, "FaultCode not served (%r / %r)" % (lo, hi)
        return lo[0] | (hi[0] << 16)

    # establish liveness -> E017 clear
    wire.feed(build_frame({0x04: (0x04, 1), 0x0d: (0x04, 1), 0x11: (0, 1), 0x12: (0, 1)}))
    assert (fault_word() & E017) == 0, "E017 set while the safety link is alive"

    # go quiet past the timeout (advance the ms clock) -> E017 raised
    sim.w32(sim.sym("g_ticks"), 2_000_000)      # >> SAFETY_LINK_TIMEOUT_MS since the last frame
    assert (fault_word() & E017) != 0, "E017 not raised after the safety link went quiet"

    # a fresh frame restores the link -> E017 clears (recovery)
    wire.feed(build_frame({0x04: (0x04, 1), 0x0d: (0x04, 1), 0x11: (0, 1), 0x12: (0, 1)}))
    assert (fault_word() & E017) == 0, "E017 did not clear after the link recovered"


def test_dsp_link_loss_raises_e000():
    """DSP-link (USART3) comms-loss supervision (docs/39 T08): the DSP polls us as a
    Modbus master on USART3, so a served poll is the liveness signal; once one has
    been seen, E000 (FaultCode bit 0, "Internal communication fault 1" — RE-confirmed
    as the DSP link, docs/30) is raised if no poll arrives within the timeout and
    clears on the next poll. Each ModbusDsp read IS a DSP poll, so the clock is
    advanced by poking g_ticks between reads. The factory threshold is sim-blocked, so
    ours uses a conservative default."""
    from arm_sim_modbus import ModbusDsp
    IR_FAULT_L, E000 = 60, 1 << 0
    sim = _ours()
    dsp = ModbusDsp(sim)                        # the DSP master on USART3

    # a first poll establishes liveness -> E000 clear
    f = dsp.read_input(IR_FAULT_L)
    assert f is not None and (f[0] & E000) == 0, "E000 set while the DSP link is alive (%r)" % f

    # go quiet past the timeout -> the next poll's reply shows E000 raised
    sim.w32(sim.sym("g_ticks"), 5_000_000)     # >> DSP_LINK_TIMEOUT_MS since the last poll
    f = dsp.read_input(IR_FAULT_L)
    assert f is not None and (f[0] & E000) != 0, "E000 not raised after the DSP link went quiet (%r)" % f

    # that poll restored liveness -> E000 clears again (recovery)
    f = dsp.read_input(IR_FAULT_L)
    assert f is not None and (f[0] & E000) == 0, "E000 did not clear after the DSP link recovered (%r)" % f


def test_bms_link_loss_raises_w000():
    """BMS/CAN comms-loss supervision (docs/39 T08): once a recognised pack frame has
    been seen, W000 (WarningCode bit 0, "Battery communication failure") is raised if
    no further pack frame arrives within the timeout and clears on the next good frame.
    Driven on CAN1 via CanBattery; the clock is advanced by poking g_ticks. The exact
    factory threshold is sim-blocked, so ours uses a conservative default."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_can import CanBattery
    IR_WARNCODE_L, W000 = 62, 1 << 0
    sim = _ours()
    battery = CanBattery(sim)           # install CAN1 hooks before boot
    mb = ModbusDongle(sim)

    def warn():
        w = mb.read_input(IR_WARNCODE_L)
        assert w, "WarningCode not served (%r)" % w
        return w[0]

    # establish liveness -> W000 clear
    battery.send_soc_soh(77, 96)
    battery.send_measurements(5325, 150, 231)
    battery.settle()
    assert (warn() & W000) == 0, "W000 set while the BMS link is alive (0x%x)" % warn()

    # go quiet past the timeout -> W000 raised
    sim.w32(sim.sym("g_ticks"), 10_000_000)    # >> BMS_LINK_TIMEOUT_MS since the last frame
    assert (warn() & W000) != 0, "W000 not raised after the BMS link went quiet"

    # a fresh pack frame restores the link -> W000 clears (recovery)
    battery.send_soc_soh(77, 96)
    battery.settle()
    assert (warn() & W000) == 0, "W000 did not clear after the BMS link recovered"


def test_w008_tracks_relayed_peer_identity():
    """W008 (FW-version mismatch) is sourced from the peer identity the safety CPU
    relays into the telemetry bank (bank+3..6): it is raised at boot and clears once a
    matching identity ("ceaa", case-insensitive) is relayed -- the same compare the
    factory classifier does (sub_0801a93a) and, like the factory health bit, LATCHED
    (a later mismatch does not re-raise it). HR 10 low mirrors the relayed DSP version
    (bank+2). Ours sources both live in the loop (src/main.c, src/safety/safety_cpu.c)."""
    from arm_sim_modbus import ModbusDongle
    IR_WARNCODE_L, HR_CNTL_FW_VER = 62, 10
    W008 = 1 << 8
    OFF_DSP_VER, OFF_IDENT = 0x02, 0x03       # safety-bank offsets (safety_cpu.h)
    sim = _ours()
    mb = ModbusDongle(sim)
    bank = sim.sym("g_safety_bank")

    def poke(ident, dsp_ver):
        sim.uc.mem_write(bank + OFF_IDENT, ident)
        sim.uc.mem_write(bank + OFF_DSP_VER, bytes([dsp_ver]))

    # A non-matching identity leaves W008 raised (and HR 10 low still tracks bank+2).
    poke(b"zzzz", 0x2a)
    warn = mb.read_input(IR_WARNCODE_L)
    assert warn and (warn[0] & W008) != 0, "W008 not raised on a mismatched peer identity (%r)" % warn
    hr10 = mb.read_holding(HR_CNTL_FW_VER)
    assert hr10 and (hr10[0] & 0xFF) == 0x2a, "HR 10 low did not mirror the relayed DSP version (%r)" % hr10

    # A case-insensitive match clears W008 (latches OK).
    poke(b"CEAA", 0x2a)
    warn = mb.read_input(IR_WARNCODE_L)
    assert warn and (warn[0] & W008) == 0, "W008 not cleared by a matching peer identity (%r)" % warn

    # Latched: a later mismatch does not re-raise it (factory parity).
    poke(b"zzzz", 0x2a)
    warn = mb.read_input(IR_WARNCODE_L)
    assert warn and (warn[0] & W008) == 0, "W008 re-raised after a match (should latch) (%r)" % warn


# --- BMS CAN -> Modbus misfiling quirks: NOT reproduced (docs/31 Q1-Q4, T11c) --
# The factory misfiles these frames (reproduced in test_arm_sim_factory_only.py);
# our decoder (src/can/bms_can.c, src/main.c on_can_frame) deliberately does not.
def test_bms_frame_misfiling_quirks_not_reproduced():
    """Q1: the 0x355 high-res SOC does NOT bleed into IR 101 (we leave MaxCellVolt
    alone -- no bogus 7.7 V cell). Q2: the 0x359 "PN" marker does NOT land in IR 97
    BatCapacity. The real datum we do publish from 0x359 -- the module count -> IR 96
    -- is still correct."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_can import CanBattery
    sim = _ours()
    bat = CanBattery(sim)
    mb = ModbusDongle(sim)
    bat.send_soc_soh(77, 96)
    bat.send_alarms(0x0102, 0x0408, pack_count=3)
    bat.settle()
    blk = mb.read_input(96, 6) or [None] * 6         # IR 96,97,...,101
    assert blk[1] == 0, "Q2 reproduced: IR 97 BatCapacity = %r, ours should leave it 0" % (blk[1],)
    assert blk[5] == 0, "Q1 reproduced: IR 101 MaxCellVolt = %r, ours should leave it 0" % (blk[5],)
    assert blk[0] == 3, "IR 96 module count = %r, expected 3 (we publish this one)" % (blk[0],)


def test_bms_alarm_b_not_decoded():
    """Q3: our firmware does not decode 0x35A at all -- injecting it changes no BMS
    input register (matching the factory, which stages but never publishes it)."""
    from arm_sim_modbus import ModbusDongle
    from arm_sim_can import CanBattery
    sim = _ours()
    bat = CanBattery(sim)
    mb = ModbusDongle(sim)
    bat.settle()
    before = mb.read_input(81, 26) or [None] * 26
    bat.send(0x35A, bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x11, 0x22]))
    bat.settle()
    after = mb.read_input(81, 26) or [None] * 26
    diff = [(81 + i, before[i], after[i]) for i in range(26) if before[i] != after[i]]
    assert not diff, "Q3: 0x35A changed BMS registers (ours should ignore it): %s" % diff


def test_fresh_boot_has_factory_defaults():
    """A truly blank config flash (erased chip, no stored records) boots with the
    factory-fresh settings defaults (T03), not zeros -- matching a fresh factory
    unit. A slot that DOES hold a record overrides its default (next test). Keep in
    sync with SETTINGS_DEFAULTS in include/inv/settings_map.h (measured ceaa-07xx
    defaults). We attach an ERASED flash (0xFF, no valid records) before boot so
    ModbusDongle does not provision the usual zero-payload records."""
    from arm_sim import SpiNorFlash
    from arm_sim_modbus import ModbusDongle
    sim = _ours()
    sim.attach_spi_flash(cs_pin="PA4", spi_base=0x40013000, flash=SpiNorFlash())
    mb = ModbusDongle(sim)                 # sees spi_flash present -> no config provisioned
    EXPECT = {23: 30, 64: 100, 65: 100, 66: 100, 99: 574, 101: 250, 102: 250,
              105: 15, 110: 1, 120: 144, 147: 150}
    bad = []
    for reg, want in sorted(EXPECT.items()):
        got = mb.read_holding(reg)
        if got != [want]:
            bad.append("HR %d: want %d got %s" % (reg, want, got))
    assert not bad, "fresh-boot defaults wrong:\n        " + "\n        ".join(bad)


def test_stored_config_overrides_default():
    """A slot that holds a record overrides the applied default (persisted value
    wins). The default ModbusDongle harness provisions valid zero-payload records
    for every slot, so the defaulted registers read their stored value (0 here),
    not the default -- proving the override path. (T03)"""
    from arm_sim_modbus import ModbusDongle
    sim = _ours()
    mb = ModbusDongle(sim)                 # provisions zero-payload records in all slots
    # 99 (slot 0) and 64 (slot 5) are in SETTINGS_MAP -> stored 0 overrides the default
    assert mb.read_holding(99) == [0], "stored (0) should override the 574 default"
    assert mb.read_holding(64) == [0], "stored (0) should override the 100 default"


def test_invreboot_enters_bootloader():
    """The ARM half of the dongle-driven firmware update (docs/43): the dongle's
    "restart inverter" command -- ResetSetting (holding reg 11) bit 7, InvReboot
    -- must make our firmware request an ARM system reset, which on a
    bootloader+App part hands control to the bootloader at 0x08000000.

    This is the black-box drive of the shared enter-bootloader contract: we feed
    the real Modbus write over the UART and let our own loop act on it (the
    factory half, which can't be driven cold, executes its NVIC_SystemReset site
    by address in test_arm_sim_factory_only.py). The sim stops at the AIRCR reset
    request so the post-reset spin never runs."""
    from arm_sim_modbus import ModbusDongle
    sim = _ours()
    rec = sim.watch_system_reset()          # observe/halt on the reset request
    mb = ModbusDongle(sim)                   # boots our firmware into its loop
    # ResetSetting.InvReboot over Modbus 0x06 -- the dongle's restart command.
    mb.write_single(HR_RESET_SETTING, INV_RESETSETTING_INV_REBOOT)
    assert_requests_bootloader(rec, "ours")
    # Our monolithic 12000XP build keeps its vector table at 0x08000000, so the
    # boot PC the core fetches after the reset is present and in flash.
    bootpc = sim.reset_vector()
    assert 0x08000000 <= bootpc < 0x08080000, \
        "reset vector (boot PC) not in flash: 0x%08x" % bootpc


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
