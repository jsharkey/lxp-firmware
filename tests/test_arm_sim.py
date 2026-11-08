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
    python3 tests/test_arm_sim.py reference/ceaa-07xx_vE_260214.bin      # factory oracle (flat .bin)

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
    sim = ArmSim(path)
    # Front-panel keys idle high (the firmware enables pull-ups; a real idle key
    # reads high, active-low). The harness does not model the pull-ups, so drive
    # them high explicitly -- as tools/factory_hmi.py does -- otherwise the keys
    # float low and read as a phantom press, which the HMI acts on. (PA8/PA11 UP/
    # DOWN, PC8/PC9 ENTER/ESC -- the factory key pins, docs/16.)
    for k in ("PA8", "PA11", "PC8", "PC9"):
        sim.set_input(k, 1)
    return sim


def _mb(sim, **kw):
    """The Modbus master for the port this image serves. ModbusDongle (UART5 --
    our firmware's dongle port) by default; ModbusDsp (USART3) when the env
    LXP_MODBUS_PORT=dsp, which the Makefile sets for the factory invocation: the
    factory's UART5 dongle RX is a scheduler task needing the RTOS (T02), so in
    the harness it answers register reads/writes on its DSP-facing USART3 slave
    (same register model). Explicit per image; no runtime auto-detection."""
    from arm_sim_modbus import ModbusDongle, ModbusDsp
    cls = ModbusDsp if os.environ.get("LXP_MODBUS_PORT") == "dsp" else ModbusDongle
    return cls(sim, **kw)


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
    ARM↔DSP link): PB10 = AF push-pull (0xB), PB11 = floating input (0x4). Both
    firmwares bring USART3 up the same way, so this is a common boot/IO smoke
    test -- proof the harness runs each image through its init, not just isolated
    functions. (The external dongle Modbus is a different port -- UART5; T01.)"""
    sim = _sim()
    sim.run_reset(max_insn=300_000)
    crh = sim.r32(0x40010C04)                 # GPIOB->CRH
    pb10 = (crh >> 8) & 0xF                    # PB10 = USART3_TX
    pb11 = (crh >> 12) & 0xF                   # PB11 = USART3_RX
    assert pb10 == 0xB, "PB10 mode nibble = 0x%x (expected 0xB AF-PP 50MHz)" % pb10
    assert pb11 == 0x4, "PB11 mode nibble = 0x%x (expected 0x4 floating input)" % pb11


def test_modbus_charge_current_write_read():
    """Dongle Modbus (docs/04): set HR 101 (ChargeCurr) to 42 with a 0x06
    write-single, read it back with a 0x03 read-holding, then overwrite it with
    43 and confirm the edit reads back. Pure wire-level black box -- frame a
    request on the UART, let the firmware's own loop answer, parse the reply --
    so the same test holds for any image that speaks the EG4 dongle protocol.

    Runs against both images on the port each serves (see _mb): ours on UART5,
    the factory on its USART3 DSP-facing slave. The master delivers that UART's
    IRQ via the RTOS engine when the firmware has armed it (arm_sim_modbus.py)."""
    HR_CHARGE_CURR = 101

    mb = _mb(_sim())

    assert mb.write_single(HR_CHARGE_CURR, 42) == 42, \
        "0x06 write of ChargeCurr=42 was not acknowledged"
    assert mb.read_holding(HR_CHARGE_CURR) == [42], \
        "0x03 read did not return the written ChargeCurr=42"

    assert mb.write_single(HR_CHARGE_CURR, 43) == 43, \
        "0x06 overwrite of ChargeCurr=43 was not acknowledged"
    assert mb.read_holding(HR_CHARGE_CURR) == [43], \
        "0x03 read did not return the edited ChargeCurr=43"


def test_can_battery_telemetry_reaches_modbus():
    """Battery BMS CAN (docs/20) -> Modbus input registers (the EG4 18kPV-12LV
    map). The pack streams telemetry on CAN1; the ARM takes it off the bus,
    caches it, and serves it over the dongle. Inject the core frames, let the
    firmware propagate them, then read the registers back and confirm each data
    point crossed with the right register and scaling:

        0x355 SOC/SOH  -> IR 5   (low byte SOC %, high byte SOH %)
        0x356 voltage  -> IR 4   (Vbat; 0.01 V -> 0.1 V, rounded)
        0x356 current  -> IR 98  (BatCurrent_BMS, 0.01 A, signed, 1:1)
        0x356 temp     -> IR 103 (MaxCellTemp_BMS, 0.1 degC, signed, 1:1)
        0x351 chg Vlim -> IR 83  (ChargeVoltRef = min(0x351, HR 99); here HR 99 is
                                  raised above the limit so it passes through 1:1)
        0x359 fault    -> IR 99  (FaultCode_BMS, protection bitfield, 1:1)
        0x359 warn     -> IR 100 (WarningCode_BMS, alarm bitfield, 1:1)
        0x359 modules  -> IR 96  (BatParallelNum, module count)

    Black box over two buses: CanBattery drives CAN1 (polled for our firmware,
    interrupt-driven for the factory) and the Modbus master drives each image's
    port (ours UART5 / factory USART3, via _mb), neither naming a symbol -- so
    the one test holds for both images."""
    from arm_sim_can import CanBattery
    SOC, SOH = 77, 96                   # -> IR 5 = (SOH<<8)|SOC
    V_CV, I_CA, T_DC = 5325, 150, 231   # 0x356: 53.25 V, 1.50 A, 23.1 degC
    CHG_V = 560                         # 0.1 V charge-V limit (below the HR 99 ceiling)
    FAULT, WARN = 0x0102, 0x0408        # 0x359 protection / alarm bitfields
    MODULES = 3                         # 0x359 [4] pack module count

    sim = _sim()
    battery = CanBattery(sim)     # install CAN1 hooks before the image runs
    mb = _mb(sim)        # boots the image + installs the UART hooks

    # IR 83 is the WORKING charge-V reference = min(0x351 limit, HR 99 ChargeVoltRef)
    # (docs/39 T11a). Raise HR 99 above CHG_V so the pack's limit passes through
    # here regardless of each image's HR 99 default (factory 574, ours blank);
    # the setting-wins branch is test_bms_charge_volt_ref_clamps_to_setting.
    mb.write_single(99, 590)

    battery.send_soc_soh(SOC, SOH)
    battery.send_measurements(V_CV, I_CA, T_DC)
    battery.send_limits(CHG_V)
    battery.send_alarms(FAULT, WARN, pack_count=MODULES)
    battery.settle()              # let the telemetry propagate into the register image

    # IR 4 (Vbat) and IR 5 (SOC/SOH) are adjacent -> one read.
    vbat, soc_soh = mb.read_input(4, 2) or [None, None]
    assert soc_soh == (SOH << 8) | SOC, "SOC/SOH -> IR 5: got %r" % (soc_soh,)
    assert vbat == (V_CV + 5) // 10,    "voltage -> IR 4 (Vbat): got %r" % (vbat,)

    # IR 83, 98, 99, 100, 103 are in one 40-register group -> one read of 83..103.
    blk = mb.read_input(83, 21) or [None] * 21
    assert blk[0]  == CHG_V,   "charge Vlim -> IR 83: got %r"  % (blk[0],)
    assert blk[13] == MODULES, "modules -> IR 96: got %r"      % (blk[13],)
    assert blk[15] == I_CA,    "current -> IR 98: got %r"      % (blk[15],)
    assert blk[16] == FAULT,   "fault -> IR 99: got %r"        % (blk[16],)
    assert blk[17] == WARN,    "warn -> IR 100: got %r"        % (blk[17],)
    assert blk[20] == T_DC,    "temperature -> IR 103: got %r" % (blk[20],)


def test_usart2_safety_frame_reaches_modbus():
    """Safety-CPU USART2 frame on the wire -> Modbus input registers (docs/33, T05).
    The redundant CPU streams an EG4 type-1 frame (SOF 0x49, big-endian, CRC-16)
    on USART2; each firmware receives it on its own RXNE-interrupt path, decodes
    the frame into its telemetry bank, and serves the measurements over Modbus. The
    SAME raw bytes feed both images and each must serve the identical input
    registers -- the factory-vs-ours oracle for the wire ingest.

    A "tag 2" record (grid/EPS/inverter block, docs/33 §1a) carries, big-endian at
    the given frame offsets, values that land at these registers (the measurement
    tags are published on every valid frame, so no link warm-up is needed):

        frame +0x17 -> IR 12  grid voltage R        +0x1d -> IR 23  EPS frequency
        frame +0x19 -> IR 15  grid frequency        +0x21 -> IR 18  inverter current (x10)
        frame +0x1b -> IR 20  EPS voltage R         +0x23 -> IR 13  grid voltage S
                                                     +0x25 -> IR 122 generator frequency

    Black box on both images: the wire feeder (Usart2SafetyWire) only serves SR/DR
    and pends the USART2 NVIC line, so every byte travels each firmware's real RX
    ISR; the Modbus master reads the served registers. Neither a symbol nor an
    internal function is named."""
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    GRID_R, GRID_F, EPS_R, EPS_F, I_INV, GRID_S, GEN_F = 2401, 5001, 2399, 5000, 1234, 2402, 6000

    sim = _sim()
    mb = _mb(sim)                              # boots the image + installs UART hooks
    wire = Usart2SafetyWire(sim, boot=False)   # share that boot; add the USART2 wire
    assert wire.rx_is_interrupt_driven(), \
        "USART2 RX is not RXNE-interrupt-driven (CR1 RXNEIE / CR3 DMAR)"

    frame = build_frame({0x14: (2, 1),
                         0x17: (GRID_R, 2), 0x19: (GRID_F, 2), 0x1b: (EPS_R, 2),
                         0x1d: (EPS_F, 2), 0x21: (I_INV, 2), 0x23: (GRID_S, 2),
                         0x25: (GEN_F, 2)})
    got = wire.feed(frame)
    assert got == len(frame), "only %d/%d USART2 bytes received on the wire" % (got, len(frame))

    for ir, exp in ((12, GRID_R), (15, GRID_F), (20, EPS_R), (23, EPS_F),
                    (18, I_INV * 10), (13, GRID_S), (122, GEN_F)):
        rd = mb.read_input(ir)
        assert rd == [exp], "fed USART2 frame -> IR %d = %r, expected [%d]" % (ir, rd, exp)


def test_gen_volt_mirrors_grid_s():
    """IR 121 (GenVolt) is served from the SAME safety-bank word as IR 13 (grid
    voltage S, +0x28): the generator input shares the S-phase sense on this image,
    so Vgen == VacS (T26, docs/33 / IR121_126-generator.md). Black box on both
    images: feed a USART2 tag-2 frame carrying grid_s at +0x23 and assert IR 121,
    IR 13 both read it. Factory-oracled on ceaa-07xx (IR 121 = IR 13 = 2402); our
    firmware serves the same mirror (safety_cpu.c PUT(IR_GEN_VOLT, +0x28)). This is
    the externally observable source for IR 121 -- IR 123/124/125 (gen power/energy)
    are ARM-computed/accumulated and are not exercised by telemetry ingest alone."""
    from arm_sim_usart2 import Usart2SafetyWire, build_frame
    GRID_S = 2398
    sim = _sim()
    mb = _mb(sim)
    wire = Usart2SafetyWire(sim, boot=False)
    frame = build_frame({0x14: (2, 1), 0x23: (GRID_S, 2)})
    got = wire.feed(frame)
    assert got == len(frame), "only %d/%d USART2 bytes received" % (got, len(frame))
    assert mb.read_input(13) == [GRID_S], "IR 13 (grid_s) did not take the fed value"
    assert mb.read_input(121) == [GRID_S], \
        "IR 121 (GenVolt) = %r, expected the grid_s mirror [%d]" % (mb.read_input(121), GRID_S)


def test_bms_charge_volt_ref_clamps_to_setting():
    """Working charge-V derivation (docs/39 T11a): the inverter serves IR 83 =
    min(0x351 charge-V limit, HR 99 ChargeVoltRef), not the pack's limit raw.

    Black-box on both images: set HR 99 below the pack's reported limit, inject a
    0x351 charge-V ABOVE the setting, and confirm the setting clamps IR 83 down to
    it. Factory-oracled on ceaa-07xx (HR 99 = 550, 0x351 = 600 -> IR 83 = 550); the
    BMS-wins branch (limit below the setting, passing through) is covered by
    test_can_battery_telemetry_reaches_modbus. HR 99 is written over the wire so
    the test does not depend on either image's HR 99 power-on default."""
    from arm_sim_can import CanBattery
    SETTING = 550                       # HR 99 ChargeVoltRef (0.1 V)
    BMS_LIMIT = 600                     # 0x351 charge-V limit (0.1 V), above the setting

    sim = _sim()
    battery = CanBattery(sim)     # install CAN1 hooks before the image runs
    mb = _mb(sim)                 # boots the image + installs the UART hooks

    mb.write_single(99, SETTING)
    battery.send_limits(BMS_LIMIT)
    battery.settle()

    ir83 = (mb.read_input(83, 1) or [None])[0]
    assert ir83 == SETTING, \
        "IR 83 should clamp to HR 99 (%d), got %r" % (SETTING, ir83)


def test_modbus_acfirst_window_tracks_rtc():
    """AC-First load-priority window vs. the ARM real-time clock (docs/25).

    Program AC-First window 0 to 06:00-08:00 by Modbus (holding regs 152/153,
    each packed (minute<<8)|hour), set the clock over the wire (regs 13/14), and
    sweep it across both edges. The firmware evaluates the window against its own
    RTC and reports "AC-First window active now" as bit 8 of *input* register 126
    -- the only externally observable signal that moves with the window (a full
    IR 0-255 scan on the factory oracle finds exactly this one). The boundary is
    start-inclusive / end-exclusive: active at 06:00, off at 08:00. Re-pointing
    the window (02:00-04:00 -> 06:00-08:00) moves the active band with it, so the
    bit tracks the configured times, not a fixed range.

    Pure wire-level black box -- frame requests on the UART, read the reply -- so
    the same spec holds for any image that speaks the EG4 dongle protocol. NB:
    input register 126 (this status word) is a *different register space* from
    holding registers 126-131 (the OptimalChg_DisChg config table): same number,
    different space, different meaning -- see docs/25.

    Runs green on both images: the factory oracle and our firmware, whose
    AC-First evaluator is src/sched/acfirst.c (pure logic host-tested in
    tests/test_acfirst.c), wired to IR 126 bit 8 in main.c."""
    HR_ACFIRST_START_0, HR_ACFIRST_END_0 = 152, 153
    HR_TIME_DATE_HOUR, HR_TIME_MIN_SEC   = 13, 14
    IR_ACFIRST_WIN_STATUS                = 126
    ACFIRST_WIN_ACTIVE                   = 1 << 8

    def enc(hour, minute):                        # window register packing
        return ((minute & 0xFF) << 8) | (hour & 0xFF)

    mb = _mb(_sim())
    mb.write_single(HR_ACFIRST_START_0, enc(6, 0))   # window 0 start 06:00
    mb.write_single(HR_ACFIRST_END_0,   enc(8, 0))   # window 0 end   08:00

    def window_active_at(hour, minute):
        mb.write_single(HR_TIME_DATE_HOUR, 1 | (hour << 8))   # date=1, hour
        mb.write_single(HR_TIME_MIN_SEC,   minute & 0xFF)     # minute, sec=0
        for _ in range(6):                  # let the periodic evaluator re-run
            mb.sim.run(300_000)
        reg = None
        for _ in range(4):                  # tolerate a transient missed reply
            got = mb.read_input(IR_ACFIRST_WIN_STATUS)
            if got:
                reg = got[0]
                break
        assert reg is not None, "no reply reading IR %d" % IR_ACFIRST_WIN_STATUS
        return bool(reg & ACFIRST_WIN_ACTIVE), reg

    # (clock, expected-active) across the 06:00-08:00 window edges
    for (h, m), exp in [((5, 59), False), ((6, 0), True),
                        ((7, 30), True),  ((8, 0), False)]:
        active, reg = window_active_at(h, m)
        assert active == exp, (
            "AC-First window 06:00-08:00 at %02d:%02d: active=%s (IR126=0x%04x), "
            "expected %s" % (h, m, active, reg, exp))


def _boot_budget(path):
    """Instructions to run before the dongle transacts. Our compact MCU image
    paints a bit-banged LCD splash at boot and needs a long pre-roll before it
    serves Modbus; the ~512 KB factory flat image boots fast, and a long pre-roll
    would instead let its *debounced* config flush fire during boot and race our
    write (leaving the slot mid-rewrite). Pick by image size -- ours is tens of
    KB, the factory flat image is hundreds."""
    return 1_000_000 if os.path.getsize(path) > 0x40000 else 5_000_000


def _persist_roundtrip(reg, value, settle=15_000_000, systick=2000):
    """Write `reg`=`value` over Modbus, let the firmware journal it to the SPI
    config flash, then COLD BOOT -- a brand-new ArmSim (fresh CPU + fresh RAM)
    whose ONLY carry-over is the flash device itself (its .mem is non-volatile
    across the power cycle, nothing else is) -- and read `reg` back.

    Returns (write_echo, flushed_to_flash, readback). `flushed_to_flash` is True
    once the firmware has programmed *something* new into the six-slot config
    region (0x0000-0xBFFF) after the write -- a black-box "a save happened"
    signal that needs no knowledge of which slot/offset the value lands in.

    SysTick is run fast (2000 insn/tick) so the firmware's debounced flush
    completes in a few million instructions instead of tens of millions."""
    path = _resolve_image()
    if not path:
        raise Skip("no image (pass one on the command line or set $LXP_SIM_IMAGE)")
    if not os.path.exists(path):
        raise Skip("image %s not found" % path)
    if is_intel_hex(path):
        raise ValueError("%s is an Intel .hex; pass a flat .bin (make factory)" % path)
    CONFIG_END = 0xC000                       # the six 8 KB slots live in 0x0..0xBFFF
    boot = _boot_budget(path)

    # --- cold boot #1: factory-provisioned config flash; write, let it flush ---
    sim1 = ArmSim(path)
    dev = sim1.attach_config_flash()          # a valid record per slot, as a programmed unit ships
    mb1 = _mb(sim1, systick=systick, boot_insn=boot)
    baseline = bytes(dev.mem[:CONFIG_END])
    echo = mb1.write_single(reg, value)
    used = 0
    while used < settle and bytes(dev.mem[:CONFIG_END]) == baseline:
        sim1.run(1_000_000)
        used += 1_000_000
    flushed = bytes(dev.mem[:CONFIG_END]) != baseline

    # --- cold boot #2: fresh CPU + RAM, SAME flash device (the only NV state) ---
    sim2 = ArmSim(path)
    sim2.attach_spi_flash(flash=dev)
    mb2 = _mb(sim2, systick=systick, boot_insn=boot)
    return echo, flushed, mb2.read_holding(reg)


def test_settings_persist_across_cold_boot():
    """A settings write must survive a power cycle through the SPI config flash.

    Black box, same contract for both images: write HR 101 (ChargeCurr), let the
    firmware journal it to flash, then cold-boot a fresh CPU/RAM against *only*
    the persisted flash and read it back -- it must still be there. This is the
    whole persistence loop (Modbus write -> settings struct -> flash record ->
    reboot -> loader -> Modbus read), end to end.

    The factory image passes. Our firmware must implement the same flash
    persistence to pass (TDD target)."""
    HR_CHARGE_CURR, value = 101, 55
    echo, flushed, got = _persist_roundtrip(HR_CHARGE_CURR, value)
    assert echo == value, \
        "0x06 write of ChargeCurr=%d was not acknowledged (echo=%r)" % (value, echo)
    assert flushed, \
        "the write never reached the config flash -- nothing was persisted"
    assert got == [value], \
        "after a cold boot, ChargeCurr read back as %r, not [%d]" % (got, value)


def test_sn_write_read_back():
    """The device serial number (HR 2-6, 10 ASCII bytes) is set with a Modbus
    write-multiple (func 0x10) -- one of only two blocks that accept 0x10 (the
    other is the time, docs/wiring HR002_006) -- and reads back over 0x03. Black
    box, both images: set a distinctive SN and read it straight back.

    (Read immediately after the write: on the factory image the USART3 fallback
    slave stops answering a little after a settings write -- the same harness limit
    the T23/T24 sweeps note -- so this pins the write+read-back; cold-boot
    persistence is covered factory-side by test_persists_sn_across_cold_boot.)"""
    SN = b"AB12345678"
    sim = _sim()
    mb = _mb(sim)
    assert mb.write_sn(SN) == 5, "0x10 SN write (HR 2-6) was not acknowledged"
    got = mb.read_sn()
    assert got == SN, "SN did not read back: got %r" % (got,)


def test_sn_persists_across_cold_boot():
    """The 0x10 SN write (HR 2-6) survives a power cycle through the SPI config
    flash -- same loop as the settings persist test but via write-multiple. Black
    box, both images: ours stores the SN at slot-0 payload 0x01 (ComAddr is the
    single byte at 0x00), the factory at the same place (T24c/T24d)."""
    SN, CONFIG_END = b"SN20261108", 0xC000
    path = _resolve_image()
    if not path or not os.path.exists(path):
        raise Skip("no image")
    if is_intel_hex(path):
        raise ValueError("%s is an Intel .hex; pass a flat .bin" % path)
    boot = _boot_budget(path)

    sim1 = ArmSim(path)
    for k in ("PA8", "PA11", "PC8", "PC9"):
        sim1.set_input(k, 1)
    dev = sim1.attach_config_flash()
    mb1 = _mb(sim1, systick=2000, boot_insn=boot)
    base = bytes(dev.mem[:CONFIG_END])
    assert mb1.write_sn(SN) == 5, "0x10 SN write not acknowledged"
    used = 0
    while used < 15_000_000 and bytes(dev.mem[:CONFIG_END]) == base:
        sim1.run(1_000_000); used += 1_000_000
    assert bytes(dev.mem[:CONFIG_END]) != base, "SN write never reached the config flash"

    sim2 = ArmSim(path)
    for k in ("PA8", "PA11", "PC8", "PC9"):
        sim2.set_input(k, 1)
    sim2.attach_spi_flash(flash=dev)
    mb2 = _mb(sim2, systick=2000, boot_insn=boot)
    got = mb2.read_sn()
    assert got == SN, "after a cold boot the SN read back as %r, not %r" % (got, SN)


def test_modbus_time_set_reads_back():
    """Set the wall clock from the dongle and confirm the device's internal RTC
    took it. The EG4 time registers are HR 12-14 (docs/04): HR 12 =
    year|(month<<8), HR 13 = day|(hour<<8), HR 14 = minute|(sec<<8). Write a full
    date-time with 0x06 writes, then read HR 12-14 back with 0x03 and confirm the
    clock reads the same time.

    Pure wire-level black box, so it holds for any EG4-dongle image. Both keep a
    real wall clock the time registers read: the factory reconstructs HR 12-14
    from its calendar 0x2000d850 (proven live -- a read follows the clock, not the
    last write), and ours serves them from g_rtc (src/rtc/rtc.c); so this confirms
    the write reached the internal RTC, not just a register echo."""
    HR_TIME_YEAR_MONTH, HR_TIME_DATE_HOUR, HR_TIME_MIN_SEC = 12, 13, 14
    yr, mon, day, hr, mn, sec = 24, 3, 15, 14, 30, 45     # 2024-03-15 14:30:45

    mb = _mb(_sim())
    assert mb.write_single(HR_TIME_YEAR_MONTH, yr | (mon << 8)) == (yr | (mon << 8)), \
        "time write HR12 (year/month) not acknowledged"
    assert mb.write_single(HR_TIME_DATE_HOUR, day | (hr << 8)) == (day | (hr << 8)), \
        "time write HR13 (date/hour) not acknowledged"
    assert mb.write_single(HR_TIME_MIN_SEC, mn | (sec << 8)) == (mn | (sec << 8)), \
        "time write HR14 (minute/sec) not acknowledged"

    got = None
    for _ in range(4):                     # tolerate a transient missed reply
        got = mb.read_holding(HR_TIME_YEAR_MONTH, 3)
        if got:
            break
    assert got, "no reply reading the time registers (HR 12-14)"
    rd = (got[0] & 0xFF, got[0] >> 8, got[1] & 0xFF, got[1] >> 8, got[2] & 0xFF, got[2] >> 8)
    assert rd == (yr, mon, day, hr, mn, sec), (
        "internal clock read back (Y,Mo,D,H,Mi,S) = %r, expected %r"
        % (rd, (yr, mon, day, hr, mn, sec)))


def test_bms_telemetry_block_tracks_updates():
    """BMS CAN -> the IR 81-106 block, swept and proven LIVE (docs/20).

    The point of `test_can_battery_telemetry_reaches_modbus` is that each frame
    lands on the right register with the right scaling. This companion proves the
    block is a live mirror, not a one-shot cache: inject a full telemetry set A,
    read the whole IR 83-103 block (one group), then inject a DIFFERENT set B and
    read again -- every register our firmware drives must move to the B value.

    The registers our publish path drives (src/main.c on_can_frame): IR 4 (Vbat),
    IR 5 (SOC/SOH), IR 83 (ChargeVoltRef), IR 96 (BatParallelNum), IR 98
    (BatCurrent), IR 99/100 (BMS fault/warn), IR 103 (MaxCellTemp). The remaining
    superset entries (IR 81/82/84/101/102/104/106) are not decoded from CAN yet
    (bms_can.c), so they are deliberately NOT asserted here -- see
    docs/wiring/ARM-UART5-dongle/IR081_106-BMS.md.

    Black box over two buses (CAN1 + the dongle UART), no symbols, so the same
    spec holds for both images."""
    from arm_sim_can import CanBattery

    # (voltage_cv, current_ca, temp_dc, soc, soh, chg_v_dv, fault, warn, modules)
    # IR 83 = min(0x351 chg-V, HR 99); we raise HR 99 to 590 below (above both
    # sets' charge-V) so the limits pass through 1:1 on both images and still
    # differ between the sets (docs/39 T11a).
    SET_A = dict(v=5325, i=250,  t=231,  soc=77, soh=96, chg=560, flt=0x0102, wrn=0x0408, mod=3)
    SET_B = dict(v=5000, i=-100, t=-50,  soc=42, soh=88, chg=552, flt=0x0000, wrn=0x0010, mod=4)

    def expected(s):
        return {
            4:   (s["v"] + 5) // 10,       # 0.01 V -> 0.1 V, rounded
            5:   (s["soh"] << 8) | s["soc"],
            83:  s["chg"],
            96:  s["mod"],
            98:  s["i"] & 0xFFFF,          # signed -> wire u16
            99:  s["flt"],
            100: s["wrn"],
            103: s["t"] & 0xFFFF,          # signed -> wire u16
        }

    sim = _sim()
    battery = CanBattery(sim)
    mb = _mb(sim)
    mb.write_single(99, 590)       # ChargeVoltRef above both sets -> limits pass 1:1

    def push_and_read(s):
        battery.send_soc_soh(s["soc"], s["soh"])
        battery.send_measurements(s["v"], s["i"], s["t"])
        battery.send_limits(s["chg"])
        battery.send_alarms(s["flt"], s["wrn"], pack_count=s["mod"])
        battery.settle()
        vbat, soc_soh = mb.read_input(4, 2) or [None, None]
        blk = mb.read_input(83, 21) or [None] * 21     # IR 83..103 (one group)
        # map register number -> value
        got = {4: vbat, 5: soc_soh}
        for reg in (83, 96, 98, 99, 100, 103):
            got[reg] = blk[reg - 83]
        return got

    got_a = push_and_read(SET_A)
    for reg, want in expected(SET_A).items():
        assert got_a[reg] == want, \
            "set A: IR %d = %r, expected %r" % (reg, got_a[reg], want)

    got_b = push_and_read(SET_B)
    for reg, want in expected(SET_B).items():
        assert got_b[reg] == want, \
            "set B: IR %d = %r, expected %r" % (reg, got_b[reg], want)

    # and the block actually moved (live mirror, not a stuck cache)
    moved = [reg for reg in expected(SET_A) if got_a[reg] != got_b[reg]]
    assert moved, "no BMS register changed between set A and set B -- image is not live"


def test_modbus_optchg_table_roundtrip():
    """HR 126-131 OptimalChg_DisChg store/read-back over the dongle (docs/25,
    docs/wiring/ARM-UART5-dongle/HR126_131-OptimalChg_DisChg.md).

    The 48-slot x 2-bit half-hour table is the one OptimalChg behaviour that is
    black-box observable on this image: writing the six table registers and
    reading them back. (Investigation showed the ceaa-07xx factory stores,
    clears and serves this table but never EVALUATES it against the clock, nor
    pushes it to the DSP -- the feature is dormant here; see docs/31 Q5. So there
    is no RTC-verdict observable to assert, only the storage round-trip.)

    Pure wire-level black box, so it holds for both images: write a distinct
    pattern into each of HR 126-131 (func 0x06), read all six back (one 0x03),
    and confirm the full table survives independently. Enable HalfHourACChrStart
    (HR 120 bit0) first, as a real configurator would, to prove the gate does not
    gate storage."""
    HR_SYS_ENABLE = 120
    TABLE = {126: 0x0001,   # Time0 = charge
             127: 0x0002,   # Time8 = discharge
             128: 0x5555,   # all eight slots = charge
             129: 0xAAAA,   # all eight slots = discharge
             130: 0x4001,   # Time0 and Time7 = charge
             131: 0x1234}   # arbitrary mixed marks

    mb = _mb(_sim())
    mb.write_single(HR_SYS_ENABLE, 0x0001)           # HalfHourACChrStartEn on
    for reg, val in TABLE.items():
        assert mb.write_single(reg, val) == val, \
            "OptimalChg write HR %d = 0x%04x not acknowledged" % (reg, val)

    got = None
    for _ in range(4):                               # tolerate a transient miss
        got = mb.read_holding(126, 6)
        if got:
            break
    assert got, "no reply reading the OptimalChg table (HR 126-131)"
    want = [TABLE[r] for r in range(126, 132)]
    assert got == want, \
        "OptimalChg table read back %r, expected %r" % (got, want)


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
