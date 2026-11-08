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
                              RTC_WALK, check_live_clock,
                              assert_requests_bootloader, BOOTLOADER_BASE,
                              FACTORY_APP_VECTOR_BASE)
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
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


# Factory 07-series inlined NVIC_SystemReset: DSB; AIRCR = VECTKEY|(PRIGROUP)|
# SYSRESETREQ; DSB; spin. Confirmed to write 0x05FA0004 to 0xE000ED0C when run.
_FACTORY_NVIC_SYSTEM_RESET = 0x0802f378


def test_invreboot_enters_bootloader():
    """The ARM half of the dongle-driven firmware update (docs/43): the factory,
    on the "restart inverter" command, issues NVIC_SystemReset, which on the
    07-series bootloader+App part hands the core to the bootloader at 0x08000000
    -- below the App's own vector table at 0x08005000. That is "enter flashing
    mode."

    The command path (ResetSetting reg 11 bit 7 over the dongle link) is RTOS/
    dongle-gated in a cold sim (docs/19/26), so -- exactly as the relay parity
    tests do -- we drive the factory's real NVIC_SystemReset site directly and
    hold it to the shared enter-bootloader contract (tests/arm_sim_contract.py).
    The reset request is confirmed from the image itself; its wiring to the
    InvReboot command rests on the EG4 spec + static RE (docs/43)."""
    sim = _factory()
    rec = sim.watch_system_reset()          # observe/halt on the reset request
    sim.uc.reg_write(UC_ARM_REG_SP, 0x2000F000)
    sim.uc.reg_write(UC_ARM_REG_LR, 0x56000001)   # STOP sentinel
    try:
        sim.uc.emu_start(_FACTORY_NVIC_SYSTEM_RESET | 1, 0, count=40)
    except Exception:
        pass                                 # watch_system_reset halts us at AIRCR
    assert_requests_bootloader(rec, "factory")
    # On this part the reset vector (0x08000000) sits BELOW the App's own vector
    # table -- i.e. it is the separate bootloader, not a re-entry of the App.
    assert BOOTLOADER_BASE < FACTORY_APP_VECTOR_BASE, (
        "bootloader base 0x%08x must sit below the App vectors 0x%08x"
        % (BOOTLOADER_BASE, FACTORY_APP_VECTOR_BASE))


# --- factory relay drive: re-pin needed before these can run (docs/18) ------
# These two tests call the factory relay deciders DIRECTLY (as isolated updaters).
# That specific approach doesn't work -- the deciders are big multi-input RTOS-task
# control functions (they read IR_STATE *and* the whole-inverter warning/fault
# status, debounce counters, config enables) and fault when entered cold. The
# addresses are all re-pinned now (T02b): IR_STATE is `0x2000d0e4+0xa0`, the PC6/PB2
# decider is `sub_08016ec6` (a real function entry), `0x2000da6c` bit 4 is the manual
# override (docs/18). (The earlier note that these were "phantoms" at `0x2000a0d8+0x90`
# was a disassembler-base artifact, corrected -- docs/18/19/22.)
#
# The full factory state->PC6 path IS now demonstrated black-box, through the running
# RTOS, by `test_usart2_mode_drives_pc6` above (feed the mode on the wire with the
# inverter healthy -> PC6 follows). So these two direct-call tests SKIP: the override
# + working-mode contracts (RELAY_OVERRIDE_TRUTH / RUN_STATES / NONRUN_STATES) are
# enforced on our implementation by tests/test_arm_sim_self_only.py, and the factory
# PC6 relay is covered black-box above -- only the isolated direct-call cross-check is
# retired as unworkable (and unnecessary).
_RELAY_REPIN = ("factory relay deciders are multi-input RTOS control functions that "
                "fault when called in isolation; the factory state->PC6 path is covered "
                "black-box by test_usart2_mode_drives_pc6, and the contracts by "
                "test_arm_sim_self_only.py (T02b, docs/39).")


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
# -> distributor -> classifier). This is the classifier half; the full mode->PC6
# relay path (needs the inverter healthy first) is test_usart2_mode_drives_pc6 below.
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


# --- the classifier is a PURE PASS-THROUGH (T06b) ------------------------------
# The two points docs/22 left open (read from a 05-series image) are now pinned on
# the 07 oracle: (1) a NON-CANONICAL mode byte is NOT canonicalised -- it appears at
# IR_STATE verbatim; (2) a relayed FAULT does NOT override IR_STATE -- it flows to
# the FaultCode (STATE+0x98) while IR_STATE stays the mode byte. A fresh boot per
# case avoids the assembler ready-flag wedge that builds up after ~8 frames in one
# boot (docs/39 T02b harness gotcha).
def _factory_ir_state_and_fault(mode, fault=0):
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    TRUST_CTR = 0x2000da3e
    STATE = 0x2000d0e4
    wire = Usart2SafetyWire(_factory())
    sim = wire.sim
    sim.w32(TRUST_CTR, (sim.r32(TRUST_CTR) & ~0xFFFF) | 0x54)
    sim.set_input("PD8", 1)
    f = {0x04: (mode, 1), 0x0d: (mode, 1)}
    if fault:
        f[0x05] = (fault, 4)                          # frame+5 -> bank+0xd0 (FaultCode)
    wire.feed_frame(f)
    sim.run(6_000_000)
    return sim.r32(STATE + 0xa0) & 0xFF, sim.r32(STATE + 0x98)   # IR_STATE, FaultCode


def test_usart2_classifier_is_pure_passthrough():
    """The 07 state classifier (sub_0801a678) is a pure pass-through, pinning the two
    points docs/22 left open (T06b): a non-canonical mode byte appears at IR_STATE
    verbatim (no canonicalisation to 0x08), and a relayed fault flows to the FaultCode
    without changing IR_STATE (no 0x02 override). Fresh boot per case. Factory-only."""
    # non-canonical bytes pass through unchanged
    for mode in (0x55, 0xff):
        st, _ = _factory_ir_state_and_fault(mode)
        assert st == mode, "non-canonical mode 0x%02x -> IR_STATE 0x%02x (expected pass-through)" % (mode, st)
    # a relayed fault leaves IR_STATE = the mode byte, and composes into the FaultCode
    st, fcode = _factory_ir_state_and_fault(0x04, fault=0x00000002)
    assert st == 0x04, "fault changed IR_STATE to 0x%02x (expected 0x04 pass-through)" % st
    assert (fcode & 0x2) != 0, "relayed fault 0x2 did not reach the FaultCode (got 0x%x)" % fcode


# --- USART2 operating-mode -> PC6 run-enable relay (T02b, docs/18, docs/39) -----
# The full state->relay path, driven black-box: the operating-mode byte fed on the
# wire flows classifier sub_0801a678 -> IR_STATE (0x2000d0e4+0xa0) -> relay decider
# sub_08016ec6 -> PC6, where PC6 = (IR_STATE >= 3) -- but ONLY when the inverter is
# healthy. PC6 otherwise blinks (state-independently) whenever an ARM-local warning
# is present. Two warnings stand in a bare harness, both now understood and cleared
# from the wire/GPIO (docs/39 T02b):
#   W008 (FW-version mismatch): the classifier case-insensitively compares bank+3..6
#     against "ceaa"; feeding a tag-0 frame with that identity clears it.
#   W006 (comms health): gates on the PD8 "detect" input (docs/16: GPIOD bit 8, read
#     by sub_0801ac2c with a ~10-tick debounce) AND bank+0xca bit 0; driving PD8 high
#     and feeding clean telemetry clears it.
# With both clear (warn=0, fault=0) the decider's clean path runs and PC6 tracks the
# fed mode. The frame-trust counter (0x2000da3e) is seeded warm as elsewhere.
def test_usart2_mode_drives_pc6():
    """A USART2 operating-mode byte fed on the wire drives PC6 (the run-enable relay)
    through the factory's real classifier + relay decider: with the inverter healthy
    (peer version "ceaa" fed on the wire, PD8 detect input high, clean telemetry),
    running modes close PC6 (=1) and standby/fault/programming open it (=0). This is
    the full T02b state->PC6 demo, black-box via the running RTOS. Factory-only."""
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    TRUST_CTR = 0x2000da3e
    WARN, FAULT = 0x2000d0e4 + 0x9c, 0x2000d0e4 + 0x98
    wire = Usart2SafetyWire(_factory())
    sim = wire.sim
    sim.w32(TRUST_CTR, (sim.r32(TRUST_CTR) & ~0xFFFF) | 0x54)   # warm the frame-trust counter
    sim.set_input("PD8", 1)                                      # safety-link detect input present
    ceaa = b"ceaa"                                               # peer version signature -> W008 clear
    wire.feed_frame({0x14: (0, 1), 0x15: (ceaa[0], 1), 0x16: (ceaa[1], 1), 0x17: (ceaa[2], 1),
                     0x18: (ceaa[3], 1), 0x19: (0x05, 1), 0x29: (0x1234, 2)})
    wire.feed_frame({0x14: (2, 1), 0x11: (0, 1), 0x12: (0, 1)})  # clean tag-2 -> W006 bank input clear
    sim.set_input("PD8", 1)
    sim.run(6_000_000)                                           # health debounce -> warns clear
    assert sim.r32(WARN) == 0 and sim.r32(FAULT) == 0, \
        "inverter not healthy: warn=0x%x fault=0x%x" % (sim.r32(WARN), sim.r32(FAULT))
    # Running modes close PC6, standby (0x00) and fault (0x01) open it. PROGRAMMING
    # (IR_STATE==2) is excluded: the decider has a special case that deliberately
    # *blinks* PC6 in programming mode (sub_08016ec6, the IR_STATE==2 branch), so it
    # is not a steady level to assert.
    for mode, exp in ((0x04, 1), (0x00, 0), (0x10, 1), (0x40, 1), (0x01, 0)):
        sim.set_input("PD8", 1)
        wire.feed(build_frame({0x04: (mode, 1), 0x0d: (mode, 1)}), settle=0)
        sim.run(2_000_000)                                      # classifier + relay decider run
        got = sim.get_output("PC6")
        kind = "running" if mode in (0x04, 0x10, 0x40, 0xC0) else "non-run"
        assert got == exp, ("USART2 mode 0x%02x (%s) on the wire -> PC6=%d, expected %d"
                            % (mode, kind, got, exp))


# --- USART2 peer identity -> W008, DSP version -> HR 10 low (T12, docs/32/33) ---
# W008 (FW-version mismatch) is the classifier's verdict on the peer identity the
# safety CPU relays in its tag-0 record (frame +0x15..+0x18 -> bank +3..6): the
# classifier (sub_0801a93a) case-insensitively compares those 4 bytes against the
# model code "ceaa" and sets health 0x2000d890 bit 10 (-> W008 clear) only on a
# match. The relayed DSP FW version (frame +0x19 -> bank +2) is served as HR 10's
# low byte (docs/32). These are the register-level facts T12 parked as "not
# observable" until the USART2 wire ran (T02); now they are. Factory-only.
def _factory_version_health_bit10(ident):
    """Boot a fresh factory, warm the safety link, feed a tag-0 safety frame whose
    identity bytes (+0x15..+0x18) spell `ident`, and return bit 10 of the health word
    0x2000d890 (the "version OK" bit the classifier's identity compare sub_0801a93a
    drives; docs/39 T02b). A fresh boot per identity keeps the two directions
    independent."""
    from arm_sim_usart2 import Usart2SafetyWire
    TRUST_CTR = 0x2000da3e
    HEALTH = 0x2000d890
    wire = Usart2SafetyWire(_factory())
    sim = wire.sim
    sim.w32(TRUST_CTR, (sim.r32(TRUST_CTR) & ~0xFFFF) | 0x54)    # warm the frame-trust counter
    sim.set_input("PD8", 1)                                      # safety-link detect present
    f = {0x14: (0, 1), 0x19: (0x05, 1), 0x29: (0x1234, 2)}
    for i, b in enumerate(ident):
        f[0x15 + i] = (b, 1)
    wire.feed_frame(f)
    wire.feed_frame({0x14: (2, 1), 0x11: (0, 1), 0x12: (0, 1)})  # a clean measurement frame
    sim.set_input("PD8", 1)
    sim.run(6_000_000)                                          # health evaluation runs
    return (sim.r32(HEALTH) >> 10) & 1


def test_usart2_identity_drives_version_health_bit():
    """W008 (FW-version mismatch) is sourced from a model-IDENTITY compare, not a
    numeric version compare: the classifier case-insensitively compares the relayed
    peer identity (tag-0 +0x15..+0x18 -> bank+3..6) against "ceaa" (sub_0801a93a) and
    sets the "version OK" bit (0x2000d890 bit 10) only on a match -- a non-matching
    identity leaves it clear. This is the pinned mechanism behind W008 (docs/39 T12,
    T02b). Each direction is a fresh boot. Factory-only.

    NOTE (open, T06b-adjacent): in this bare harness the health bit does NOT surface
    as a WarningCode bit at STATE+0x9c (it stays 0 either way), so how the version-OK
    bit gates into the Modbus WarningCode is not yet pinned -- only the identity->
    health-bit step is proven here."""
    assert _factory_version_health_bit10(b"ceaa") == 1, \
        "version-OK health bit not set for a matching peer identity 'ceaa'"
    assert _factory_version_health_bit10(b"zzzz") == 0, \
        "version-OK health bit set for a non-matching peer identity 'zzzz'"


def test_usart2_dsp_version_reaches_hr10_low():
    """The DSP firmware version the safety CPU relays (tag-0 frame +0x19 -> bank+2)
    is served as HR 10's low byte (docs/32). Feed a tag-0 frame carrying a version
    byte and read HR 10 back over Modbus. Factory-only (docs/39 T12)."""
    from arm_sim_usart2 import Usart2SafetyWire
    from arm_sim_modbus import ModbusDsp
    HR_CNTL_FW_VER = 10
    sim = _factory()
    mb = ModbusDsp(sim)                               # boots the RTOS + config flash
    wire = Usart2SafetyWire(sim, boot=False)          # share that one boot
    sim.w32(0x2000da3e, (sim.r32(0x2000da3e) & ~0xFFFF) | 0x54)
    # tag-0 with identity "ceaa" and DSP version 0x2a at frame +0x19.
    wire.feed_frame({0x14: (0, 1), 0x15: (ord('c'), 1), 0x16: (ord('e'), 1),
                     0x17: (ord('a'), 1), 0x18: (ord('a'), 1), 0x19: (0x2a, 1)})
    sim.run(2_000_000)
    rd = mb.read_holding(HR_CNTL_FW_VER)
    assert rd is not None and (rd[0] & 0xFF) == 0x2a, \
        "relayed DSP version 0x2a did not reach HR 10 low (got %r)" % rd


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


# --- BMS CAN -> Modbus misfiling quirks (docs/31 Q1-Q4, T11c) ----------------
# The factory reproduces these; our firmware deliberately does not (asserted in
# test_arm_sim_self_only.py). Oracled black-box on ceaa-07xx: these tests ARE the
# factory spec for each quirk, so docs/31's verdicts are enforced, not just prose.
def test_bms_frame_misfiling_quirks_q1_q2():
    """Q1: the 0x355 high-res SOC word [4:5] (=SOC x100) bleeds into IR 101
    MaxCellVolt_BMS (the real cell-V source frame 0x373 is never wired up). Q2: the
    fixed "PN" ASCII marker in 0x359 [5:6] lands in IR 97 BatCapacity. The adjacent
    0x359 module count -> IR 96 is handled correctly, isolating Q2 to the marker."""
    from arm_sim_modbus import ModbusDsp
    from arm_sim_can import CanBattery
    sim = _factory()
    bat = CanBattery(sim)
    mb = ModbusDsp(sim)
    bat.send_soc_soh(77, 96)                 # hi-res SOC = 7700
    bat.send_alarms(0x0102, 0x0408, pack_count=3)
    bat.settle()
    blk = mb.read_input(96, 6) or [None] * 6     # IR 96,97,...,101
    assert blk[1] == 0x4E50, "Q2: 0x359 'PN' -> IR 97 = %r, expected 0x4E50 (20048)" % (blk[1],)
    assert blk[5] == 7700,   "Q1: 0x355 hi-res SOC -> IR 101 = %r, expected 7700" % (blk[5],)
    assert blk[0] == 3,      "sanity: 0x359 module count -> IR 96 = %r, expected 3" % (blk[0],)


def test_bms_alarm_b_reaches_no_register_q3():
    """Q3: the 0x35A alarm frame is received and staged but surfaces on NO Modbus
    input register. Snapshot IR 81-106, inject only 0x35A with distinctive bytes,
    and confirm nothing in the BMS block moved."""
    from arm_sim_modbus import ModbusDsp
    from arm_sim_can import CanBattery
    sim = _factory()
    bat = CanBattery(sim)
    mb = ModbusDsp(sim)
    bat.settle()
    before = mb.read_input(81, 26) or [None] * 26    # IR 81..106
    bat.send(0x35A, bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x11, 0x22]))
    bat.settle()
    after = mb.read_input(81, 26) or [None] * 26
    diff = [(81 + i, before[i], after[i]) for i in range(26) if before[i] != after[i]]
    assert not diff, "Q3: 0x35A changed BMS registers (should reach none): %s" % diff


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


# --- SN (HR 2-6) persists across a cold boot (T24c) -------------------------
# The factory journals a 0x10 SN write to the config flash (docs/23: slot-0 record)
# and restores it at boot. The full loop: 0x10 write -> settings struct -> flash
# record -> cold boot (fresh CPU/RAM, SAME flash) -> loader -> read back. Our
# firmware does the in-session 0x10 round-trip (test_sn_write_read_back) but does
# NOT yet persist the SN (HR 2-6 are not in the pinned SETTINGS_MAP; the on-flash
# SN offset vs ComAddr still needs pinning) -- a documented follow-up, so this is
# factory-only.
def test_persists_sn_across_cold_boot():
    """Factory: a 0x10 SN write to HR 2-6 survives a power cycle through the SPI
    config flash -- write, let it flush, cold-boot a fresh machine against only the
    persisted flash, and read the SN back."""
    from arm_sim_modbus import ModbusDsp
    SN, CONFIG_END = b"AB12345678", 0xC000
    KEYS = ("PA8", "PA11", "PC8", "PC9")     # idle-high, else phantom key presses
    sim1 = _factory()
    for k in KEYS:
        sim1.set_input(k, 1)
    dev = sim1.attach_config_flash()
    mb1 = ModbusDsp(sim1, systick=2000, boot_insn=4_000_000)
    base = bytes(dev.mem[:CONFIG_END])
    assert mb1.write_sn(SN) == 5, "0x10 SN write not acknowledged"
    used = 0
    while used < 15_000_000 and bytes(dev.mem[:CONFIG_END]) == base:
        sim1.run(1_000_000); used += 1_000_000
    assert bytes(dev.mem[:CONFIG_END]) != base, "SN write never reached the config flash"

    sim2 = _factory()
    for k in KEYS:
        sim2.set_input(k, 1)
    sim2.attach_spi_flash(flash=dev)         # only the flash carries over
    mb2 = ModbusDsp(sim2, systick=2000, boot_insn=4_000_000)
    got = mb2.read_sn()
    assert got == SN, "after a cold boot the SN read back as %r" % (got,)


# --- zero-dependency runner (same invocation style as test_arm_sim.py) ------
def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        _IMAGE[0] = args[0]
    return run_tests("Factory-image-only tests", _IMAGE[0] or "<none>", globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
