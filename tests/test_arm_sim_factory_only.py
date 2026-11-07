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

    python3 tests/test_arm_sim_factory_only.py reference/ceaa-07xx_vE_260214.bin

The factory image is never committed (it is proprietary); with no image argument
the tests SKIP. Needs `pip install unicorn`.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_contract import (RELAY_OVERRIDE_TRUTH, RUN_STATES, NONRUN_STATES,
                              SAFETY_TELEMETRY, SAFETY_TELEMETRY_A, SAFETY_TELEMETRY_B,
                              RTC_WALK, check_live_clock)
from arm_sim_runner import Skip, run_tests

# Factory flat-.bin image under test. Set by the __main__ runner from argv.
_IMAGE = [None]


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


# --- factory relay drive: re-pin needed before these can run (docs/18) ------
# These two tests drive the factory relay deciders directly. The addresses are now
# re-pinned (T02b): IR_STATE is `0x2000d0e4+0xa0` (verified -- the PC6/PB2 decider
# `sub_08016ec6`, a real function entry, reads exactly that byte to gate PC6), and
# `0x2000da6c` bit 4 is the manual relay override (docs/18). (The earlier note that
# these were "phantoms" and that IR_STATE lived at `0x2000a0d8+0x90` was a
# disassembler-base artifact, now corrected -- docs/18/19/22.) But the deciders
# still can't be exercised as the isolated updaters these tests assume: they are
# big multi-input RTOS-task control functions that read IR_STATE *and* the
# whole-inverter warning/fault status (the ARM-local struct `0x2000d890`), debounce
# counters and config enables. PC6 in particular blinks (state-independently)
# whenever a warning is present, and those warnings gate on `0x2000d890` -- which no
# single injected input or lone USART2 feed clears (T02b, docs/39). So a clean
# black-box factory drive isn't available without modelling that whole context.
#
# So these SKIP: the same override + working-mode contracts (RELAY_OVERRIDE_TRUTH /
# RUN_STATES / NONRUN_STATES) are enforced on our implementation by
# tests/test_arm_sim_self_only.py, so the behaviour is covered; only the
# factory-oracle cross-check is paused. (The wire->IR_STATE half of the factory
# path IS covered black-box by test_usart2_mode_reaches_ir_state above.)
_RELAY_REPIN = ("factory relay deciders are multi-input RTOS control functions "
                "(PC6 = sub_08016ec6 reads IR_STATE 0x2000d0e4+0xa0 but blinks on "
                "whole-inverter warnings in 0x2000d890 that a lone input can't "
                "clear -- T02b, docs/39); can't be driven as isolated updaters. "
                "Contract still enforced in test_arm_sim_self_only.py.")


def test_relay_override_drives_transfer_pins():
    """Manual/AutoTest relay override (docs/18): a command word drives PA12 (bit 1)
    and PB3 (bit 0) in manual mode, ignored otherwise. SKIPPED on the factory side
    pending a relay-decider re-pin (see above); enforced on ours in the self-only
    suite."""
    raise Skip(_RELAY_REPIN)


def test_relay_follows_working_mode():
    """The run-enable relay (PC6) is closed in a running operating mode and open in
    standby/fault/programming (docs/18). SKIPPED on the factory side pending a
    relay-decider re-pin (see above); enforced on ours in the self-only suite."""
    raise Skip(_RELAY_REPIN)


# --- safety-CPU telemetry -> Modbus input registers (docs/30, docs/33) ------
# The factory decodes the safety CPU's USART2 telemetry into its bank at
# 0x2000ce5c (docs/33; this base has 22 literal refs in the image, 0x20009e54 has
# zero -- the earlier 0x20009e54 was a mis-transcription that made this test fail).
# This test presents the telemetry already decoded in the bank -- where the
# factory's own register getter reads it -- and reads it back over the dongle, so
# the getter + scaling + Modbus serialisation exercised are entirely the factory's
# (arm_sim_safety.py). The *wire* half (raw USART2 bytes -> this same bank -> IR,
# through the real RX ISR) is proved end to end by test_usart2_frame_reaches_modbus
# below; this one covers the full per-field contract (all tags) that one frame
# cannot carry at once.
FAC_SAFETY_BANK = 0x2000ce5c


def _safety_factory():
    from arm_sim_modbus import ModbusDsp
    from arm_sim_safety import FakeSafetyCpu
    sim = _factory()
    return FakeSafetyCpu(sim, FAC_SAFETY_BANK, ModbusDsp(sim))


def test_safety_cpu_telemetry_reaches_modbus():
    """Safety-CPU telemetry (grid/PV/bus V, frequency, radiator temps, inverter
    current) must reach the dongle's Modbus input registers with the right
    register and scaling, and must TRACK CHANGES over time (a second, fluctuated
    snapshot reads back its new values -- the register image is live, not a
    one-shot cache). The factory image is the oracle for the shared telemetry
    contract (SAFETY_TELEMETRY); our side is in test_arm_sim_self_only.py."""
    fake = _safety_factory()
    for label, snapshot in (("A", SAFETY_TELEMETRY_A), ("B", SAFETY_TELEMETRY_B)):
        fake.send(snapshot)
        for name, raw in snapshot.items():
            _off, ir, _sc = SAFETY_TELEMETRY[name]
            exp = fake.expected(name, raw)
            got = fake.served(name)
            assert got == exp, ("factory snapshot %s: %s -> IR %d = %r, expected "
                                "%r (raw %d)" % (label, name, ir, got, exp, raw))


# --- USART2 safety-CPU wire reception (docs/39 T02a, docs/19) ------------------
# The safety CPU streams its telemetry frame on USART2; the factory receives it
# interrupt-driven on RXNE (NOT DMA -- CR1 RXNEIE set, CR3 DMAR clear, T02 RE in
# docs/19). The wire feeder (tests/arm_sim_usart2.py) only serves SR/DR and pends
# the NVIC line, so every byte travels through the firmware's own RX ISR. The full
# ingest chain is cracked (docs/33): RX ISR sub_0801bddc -> assembler sub_0801bb0e
# (SOF 0x49, CRC-16/MODBUS) -> distributor sub_0802677a + tag parser sub_08025ab8
# -> bank 0x2000ce5c -> the factory's register getter -> Modbus IR. Factory-only
# (our USART2 driver is T05).
def test_usart2_rx_receives_wire_bytes():
    """Feeding the safety-CPU USART2 stream on the wire reaches the factory's real
    RX ISR: the RX is RXNE-interrupt-driven (not DMA), and every byte fed through
    SR/DR + the pended IRQ is read by the firmware. Proves the byte-reception half
    of the USART2 ingest end to end (docs/39 T02a / T05)."""
    from arm_sim_usart2 import Usart2SafetyWire
    wire = Usart2SafetyWire(_factory())
    assert wire.rx_is_interrupt_driven(), \
        "factory USART2 RX is not RXNE-interrupt-driven (CR1 RXNEIE / CR3 DMAR)"
    data = bytes(range(0x40, 0x40 + 32))
    got = wire.feed(data)
    assert got == len(data), \
        "firmware received %d of %d USART2 bytes over the RX-ISR wire path" % (got, len(data))


def test_usart2_frame_reaches_modbus():
    """The WHOLE USART2 ingest, end to end on the wire: a valid EG4 type-1 safety
    frame fed byte-by-byte through the real RX ISR is assembled, CRC-checked,
    distributed and tag-parsed by the firmware into its telemetry bank, and the
    decoded measurements come back out as the right Modbus input registers -- with
    NO bank seeding. This closes T02a (feed USART2 bytes -> IR changes).

    The frame carries a "tag 2" record (grid/EPS/inverter block, docs/33): frame
    offsets +0x17/+0x19/+0x1b/+0x21/+0x23 (big-endian u16) land at bank
    +0x20/+0x5e/+0x22/+0x24/+0x28 and serve as IR 12/15/20/18/13. A second frame
    with new values must read back new IRs (live, not cached)."""
    from arm_sim_usart2 import Usart2SafetyWire
    from arm_sim_modbus import ModbusDsp
    sim = _factory()
    mb = ModbusDsp(sim)                          # boots the RTOS + config flash
    wire = Usart2SafetyWire(sim, boot=False)     # share that one boot
    assert wire.rx_is_interrupt_driven()

    def tag2(grid_r, grid_freq, eps_r, inv_curr, grid_s):
        return {0x14: (2, 1), 0x17: (grid_r, 2), 0x19: (grid_freq, 2),
                0x1b: (eps_r, 2), 0x21: (inv_curr, 2), 0x23: (grid_s, 2)}

    # IR -> (field, raw) for a snapshot; IR 18 (inverter current) is served x10.
    for label, (gr, gf, er, ic, gs) in (("A", (2401, 5001, 2399, 1234, 2402)),
                                        ("B", (2301, 4999, 2300, 999, 2302))):
        got = wire.feed_frame(tag2(gr, gf, er, ic, gs))
        assert got == 0x3f, "frame %s: only %d/%d bytes received on the wire" % (label, got, 0x3f)
        for ir, exp in ((12, gr), (15, gf), (20, er), (18, ic * 10), (13, gs)):
            rd = mb.read_input(ir)
            assert rd == [exp], ("frame %s: fed wire frame -> IR %d = %r, expected [%d]"
                                 % (label, ir, rd, exp))


# --- USART2 operating-mode -> IR_STATE (T02b, docs/18, docs/22, docs/39) --------
# The safety frame's operating-mode byte (frame[+4]) flows wire -> bank+0 ->
# classifier sub_0801a678 -> IR_STATE (0x2000d0e4+0xa0, which the PC6 run-enable
# relay decider reads). The distributor only publishes the mode once the safety
# link's frame-trust counter (0x2000da3e) is warm (>= 0x54, which ~85 valid frames
# reach naturally -- docs/39 T02b); we seed that counter to the warm state (as
# test_safety_cpu_telemetry_reaches_modbus seeds the bank) so the test is fast,
# while the mode byte still travels the full real path (RX ISR -> assembler -> CRC
# -> distributor -> classifier). (A clean mode->PC6 is NOT reachable from USART2
# alone: PC6 blinks whenever ARM-local warnings are present, and those gate on the
# whole-inverter status struct 0x2000d890 the USART2 peer can't clear -- docs/39.)
def test_usart2_mode_reaches_ir_state():
    """A USART2 operating-mode byte fed on the wire reaches the factory's state
    classifier: IR_STATE (0x2000d0e4+0xa0) tracks the fed mode across run and
    non-run values, through the real RX-ISR ingest. Factory-only (docs/39 T02b)."""
    from arm_sim_usart2 import Usart2SafetyWire
    TRUST_CTR = 0x2000da3e
    IR_STATE  = 0x2000d0e4 + 0xa0
    wire = Usart2SafetyWire(_factory())
    wire.sim.w32(TRUST_CTR, (wire.sim.r32(TRUST_CTR) & ~0xFFFF) | 0x54)   # warm link
    for mode in (0x04, 0x00, 0x10, 0x40, 0x02, 0x01):
        wire.feed_frame({0x04: (mode, 1), 0x0d: (mode, 1)})
        wire.sim.run(4_000_000)                       # distributor + classifier run
        got = wire.sim.r32(IR_STATE) & 0xFF
        assert got == mode, ("fed USART2 mode 0x%02x on the wire -> IR_STATE 0x%02x "
                             "(expected 0x%02x)" % (mode, got, mode))


# --- the per-pack register bank (undocumented IR 5000+), docs/34 §2b -----------
# The firmware has a per-pack register bank: the parser sub_080205d4 stores CAN
# frames (id = 0x400 | (subtype<<5) | pack) into a per-pack array (0x2000691c,
# stride 0x36), marks the pack present (0x2000a770 / count 0x2000a8ae), and the
# serializer routes INPUT registers 5000-5126 to a separate getter (sub_08020cc0)
# that serves it -- 30 slots/pack (bases 5000/5030/5060/5090), paged for >4 packs.
# NOTE: this bank is fed ONLY by CAN 0x4xx. The attached EG4-LL pack emits per-pack
# telemetry on 0x3xx (parsed to internal scalars, not served), so the bank is
# DORMANT with that pack. This test therefore drives the FIRMWARE PATH with
# synthetic 0x4xx frames -- it proves the 0x4xx -> array -> 5000-register serving
# chain works, not that this battery feeds it (it does not; docs/34 §2b).
def _inject_pack(bat, pack, subtype, data8):
    bat.send(0x400 | (subtype << 5) | (pack & 0x1F), bytes(data8))


def test_per_pack_telemetry_reaches_modbus():
    """The firmware's per-pack register path (CAN 0x4xx -> IR 5000+) works: inject
    synthetic per-pack frames (id 0x400|sub<<5|pack) for two packs and read them
    back over the dongle -- pack 0 in the 5000 block, pack 1 in the 5030 block,
    fields in frame order (reg 5000 = pack-0 subtype-0 bytes[0:2], 5001 = bytes[2:4],
    5004 = subtype-1 bytes[0:2]); a changed snapshot reads back new values (live, not
    cached). Factory-only. NB this proves the serving PATH, not that the attached
    EG4-LL pack feeds it -- that pack emits 0x3xx, leaving this bank dormant (docs/34)."""
    import struct as _s
    from arm_sim_modbus import ModbusDsp
    from arm_sim_can import CanBattery

    def snapshot(p0s0_a, p0s0_b, p0s1, p1s0):
        sim = _factory()
        bat = CanBattery(sim)
        mb = ModbusDsp(sim)
        bat.send_soc_soh(77, 96)                       # keep the aggregate block alive
        _inject_pack(bat, 0, 0, _s.pack("<HH", p0s0_a, p0s0_b) + b"\x00\x00\x00\x00")
        _inject_pack(bat, 0, 1, _s.pack("<H", p0s1) + b"\x00" * 6)
        _inject_pack(bat, 1, 0, _s.pack("<H", p1s0) + b"\x00" * 6)
        bat.settle()
        return mb.read_input(5000, 8), mb.read_input(5030, 8)

    p0, p1 = snapshot(0x1234, 0xABCD, 0x5678, 0x9ABC)
    assert p0[0] == 0x1234, "pack0 subtype0[0:2] -> IR 5000 = %r" % (p0[0],)
    assert p0[1] == 0xABCD, "pack0 subtype0[2:4] -> IR 5001 = %r" % (p0[1],)
    assert p0[4] == 0x5678, "pack0 subtype1[0:2] -> IR 5004 = %r" % (p0[4],)
    assert p1[0] == 0x9ABC, "pack1 subtype0[0:2] -> IR 5030 = %r" % (p1[0],)

    # Live, not cached: a changed snapshot reads back the new values.
    q0, _q1 = snapshot(0x1111, 0x2222, 0x3333, 0x4444)
    assert q0[0] == 0x1111 and q0[1] == 0x2222, \
        "per-pack registers did not track a change: IR 5000/5001 = %r" % (q0[:2],)


# --- RTC software calendar: walk the clock forward (docs/36) ----------------
# The factory's 1 s RTC tick/calendar-advance is sub_08018bc0; the calendar is a
# 7-byte struct at 0x2000d850 (+0 s,+1 min,+2 hr,+3 day,+4 mon,+5 yr,+6 wd) and a
# prescaler byte at 0x2000dba7 makes it advance every 2nd call (2 calls = +1 s).
# We register it with the simulator's RTC control (sim.configure_rtc / set_rtc /
# advance_rtc) and run the shared RTC_WALK contract -- the SAME vectors our
# firmware is held to in test_arm_sim_self_only.py. Self-contained: no boot.
#
# This clock is the foundation every time-of-day feature keys off -- including
# the energy-counter DAILY ROLLOVER at IR 28-37
# (docs/wiring/ARM-UART5-dongle/input-028_059-energy-counters.md), a FOLLOW-UP still blocked
# on locating that image's energy struct/accumulator (RE hand-off in docs/36).
FAC_RTC_TICK     = 0x08018bc0
FAC_CALENDAR     = 0x2000d850
FAC_RTC_PRESCALE = 0x2000dba7


def _factory_rtc():
    """A factory sim with its RTC registered; SKIPs if this image's clock does
    not behave as ceaa-07xx (e.g. the 05-series reference/ceaa-07xx_vE_260214.bin, whose RTC
    advance is a different function) -- per-image discipline, like the timewindow
    profiles."""
    sim = _factory()
    sim.configure_rtc(FAC_CALENDAR, FAC_RTC_TICK, FAC_RTC_PRESCALE, calls_per_sec=2)
    try:
        sim.set_rtc(0, 0, 0, 1, 1, 24)
        sim.advance_rtc(1)
    except Exception as e:                       # wrong image can fault the call
        raise Skip("RTC tick probe faulted (not ceaa-07xx?): %s" % e)
    if sim.get_rtc() != (1, 0, 0, 1, 1, 24):
        raise Skip("RTC tick 0x%08x did not advance 0x%08x by 1 s -- image is not "
                   "ceaa-07xx_vE_260214 (07-series-specific, docs/36)"
                   % (FAC_RTC_TICK, FAC_CALENDAR))
    return sim


def test_rtc_calendar_walks_forward():
    """Walk the factory RTC forward across second/minute/hour/day/month/year and
    leap boundaries (the shared RTC_WALK contract) and confirm the calendar
    accumulates correctly. The factory image is the oracle; our firmware is held
    to the same vectors in test_arm_sim_self_only.py.

    07-series-specific (addresses in docs/36); SKIPs on other images."""
    sim = _factory_rtc()
    for label, start, secs, exp in RTC_WALK:
        sim.set_rtc(*start)
        sim.advance_rtc(secs)
        got = sim.get_rtc()
        assert got == exp, ("factory RTC walk %s: from %r +%ds = %r, expected %r"
                            % (label, start, secs, got, exp))


def test_rtc_is_live_clock():
    """Drive the factory RTC forward and confirm a dongle read reflects it: its
    Modbus time registers reconstruct from the live calendar, not an echo of the
    last write (the shared check_live_clock contract). 07-series-specific; SKIPs
    on other images."""
    from arm_sim_modbus import ModbusDsp
    sim = _factory_rtc()
    check_live_clock(sim, ModbusDsp)         # factory answers on USART3 in the harness


# --- zero-dependency runner (same invocation style as test_arm_sim.py) ------
def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        _IMAGE[0] = args[0]
    return run_tests("Factory-image-only tests", _IMAGE[0] or "<none>", globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
