# inverter-com-fw — open-source firmware for the inverter's ARM "com" MCU

An open, C-language reimplementation of the **communications / HMI / supervisor**
firmware (the ARM Cortex-M "com" processor) of EG4 all-in-one solar off-grid
inverters. The goal is a codebase the community can read, build, flash, and
extend with new features.

**Supported variants: EG4 12000XP, EG4 18kPV, and EG4 6000XP.**
Reverse-engineering the factory ARM images proves they are the **same codebase**
on the **same MCU** (STM32F1-compatible, M4-class core — see below), differing only in a
short, enumerable set of ways — flash/boot layout, MPPT count (2 vs 3), and
hybrid grid-tie features. Those deltas are captured as a **variant descriptor**
(`include/inv/variant.h`), so the firmware is written once and branched on data,
not `#ifdef`s. See [`docs/10-18kpv-vs-12000xp.md`](docs/10-18kpv-vs-12000xp.md)
and [`docs/12-6000xp.md`](docs/12-6000xp.md).

> The Modbus spec on hand is the **18kPV-12LV** map, which the 12000XP shares as
> a **subset**: the 12000XP is non-hybrid with 2 MPPTs, so the 3rd-tracker
> registers (`Vpv3/Ppv3/Epv3*`) and hybrid-only items are inactive on it. The
> active variant is selected at build time (and keyed in the factory image by a
> 4-char `Model` code: `ceaa`=12000XP, `FAAB`=18kPV).

The device has **multiple processors**: a TI C2000 **Control DSP**, this STM32
**Communication/HMI MCU** (what this project reimplements), a **redundant
safety CPU**, and a dedicated **`mppt` power-stage controller** (a separate,
smaller STM32G0-class Cortex-M0+, newly characterized — see
[`docs/13-mppt-controller.md`](docs/13-mppt-controller.md)). The vendor splits
its firmware by role (`com` / `dsp` / `mppt`). We reimplement only the
Communication MCU.

> **Scope:** this project reimplements only the **ARM "com" MCU**. The TI C2000
> DSP that runs the real-time power electronics is intentionally left untouched;
> our firmware talks *to* it over the existing link.

## Status: bootstrapping (reverse-engineering the spec)

This is an early-stage effort. There is a verified understanding of the target
and a recovered data model — but **not yet** a buildable replacement firmware.
Honest picture of where things stand:

- [x] Confirm target MCU and memory map → **STM32F1-compatible, M4-class core** (ARMv7E-M: the factory runs `smlabb`/`sdiv`, undefined on M3 — most likely a **GD32F303-style F1 clone**; first read as "STM32F103/M3", corrected via dynamic RE), flash `0x08000000`, RAM `0x20000000` (see [`docs/01-firmware-analysis.md`](docs/01-firmware-analysis.md), [`docs/19`](docs/19-gpio-test-harness.md))
- [x] Confirm the image is **not encrypted/compressed** (reimplementation is feasible)
- [x] Identify the product → **EG4 12000XP** (Modbus spec shared with the 18kPV-12LV superset)
- [x] **Add a second variant → EG4 18kPV** (3 MPPT, hybrid): proved same MCU + codebase from the factory `App.hex`; captured the deltas as a build-selectable variant descriptor (see [`docs/10-18kpv-vs-12000xp.md`](docs/10-18kpv-vs-12000xp.md), `include/inv/variant.h`, `make VARIANT=18kpv`)
- [x] **Track 12000XP revisions over time** → `ceaa-05xx` (2025-03) vs `ceaa-07xx` (2026-02): the 07 series moved to a **bootloader + App** layout (vectors relocated `0x08000000`→`0x08005000`), and added generator scheduling / quick-charge / smart-load / resume-SOC / buzzer menus — mapped to the vendor changelog (see [`docs/11-12000xp-revisions.md`](docs/11-12000xp-revisions.md))
- [x] **Add a third variant → EG4 6000XP** (`ccaa`): same MCU + codebase (07-era), same bootloader + App layout as the 12000XP 07-series (vectors @`0x08005000`, 20 KB bootloader); added as a build target `make VARIANT=6000xp` (see [`docs/12-6000xp.md`](docs/12-6000xp.md))
- [x] **Identify a distinct `mppt` power-stage controller image** (`CBAA`): *not* a com-MCU variant — a smaller **STM32G0-class Cortex-M0+ (128 KB)** running a bare-metal **TIM1-PWM + DMA-sampled-ADC** control loop (zero HMI strings; only DMA1 + USART1 interrupts), that publishes telemetry to another chip over a **Modbus-family UART link** (standard Modbus RTU CRC-16 tables, big-endian registers). A separate peer processor for the solar DC-DC stage (see [`docs/13-mppt-controller.md`](docs/13-mppt-controller.md))
- [x] Recover the data model with **authoritative** values — states, faults, warnings, telemetry (see `include/inv/` and [`docs/02-recovered-model.md`](docs/02-recovered-model.md))
- [x] **External Modbus-RTU map fully specified** → [`include/inv/modbus_map.h`](include/inv/modbus_map.h) (the comms layer is now a known interface)
- [x] Static function map — **1211 functions, ~72% of image is code** (see [`docs/03-function-map.md`](docs/03-function-map.md))
- [x] Reverse-engineering tooling (`tools/`)
- [ ] Confirm exact part number / flash+RAM size (from the schematic you're providing)
- [x] Recover the HMI **menu tree** → `include/inv/hmi_menu.h` (95-item ordered enum) + `reference/string_catalog.txt` (442 strings). Finding: text is packed NUL-separated blobs indexed by ordinal, not `char*` tables
- [ ] Bind menu items → handler functions (needs TBB/TBH switch-table decoding)
- [ ] Document the **ARM↔DSP internal protocol** (the remaining hard interface)
- [x] **Buildable skeleton** → `make` produces a valid flashable `build/firmware.bin` (correct vector table, 72 MHz clock init, boots at `0x08000000`)
- [x] Seed recovered symbol names (`reference/symbols_named.csv`, `reference/ghidra_rename.py`)
- [x] **Modbus-RTU slave** — engine + UART port + host tests (`make test`, see [`docs/04-modbus.md`](docs/04-modbus.md)). *Port note:* the engine is currently bound to **USART3** in our skeleton; the factory serves the external dongle's EG4-Modbus on **UART5** (USART3 is the ARM↔DSP link), so the port binding is slated to move USART3→UART5 — see [`docs/26-dongle-firmware.md`](docs/26-dongle-firmware.md)
- [x] **Interrupt-driven UART** — RX/TX ring buffers serviced from the USART3 ISR, mirroring the factory's interrupt-driven UART mechanism (USART3 is its only vectored UART — the DSP link); lock-free SPSC ring (`inv/ringbuf.h`, host-tested). CAN1 (battery bus) stays **polled**, as the factory does. See [`docs/21-firmware-architecture.md`](docs/21-firmware-architecture.md)
- [x] **HMI menu system** — data-driven menu engine + model + host-tested navigation (see [`docs/06-hmi.md`](docs/06-hmi.md))
- [x] **Factory graphic HMI runs in the emulator** — reverse-engineered the factory LCD (a **240×160 monochrome MIPI-DCS LCD bit-banged 4-wire on GPIOB** (1bpp, 8 px/byte): PB12 SCLK / PB13 SDA / PB14 DC / PB15 /CS — *not* SPI1, which is the config flash; corrects the `docs/16` "status-LED" guess) and modelled it, so the factory image's **own display code** paints its real **overview** and **Common settings** screens under the harness, navigated by the real front-panel keys. On-screen app (`make factory-hmi`), ~18 s boot / ~6 s per key after a harness speed-up. The simulator is **firmware-agnostic** (`make hmi-sim [FIRMWARE=App.hex]`): with no image it runs the open-source build, and our firmware now drives the **same** panel in the same wire format (`src/hmi/lcd_tft.c`), posting a "Hello World!" as the first milestone toward a drop-in replacement. See [`docs/28-factory-hmi.md`](docs/28-factory-hmi.md)
- [x] **HMI runs on screen** — the firmware's LCD + keypad **port implemented** (20×4 HD44780 over a bit-banged PCF8574 I²C backpack; keys on the factory pins PA8/PA11/PC8/PC9) and driven end-to-end in the emulator by an **interactive app** (`make hmi`): it renders what the running firmware draws and feeds the four front-panel keys as on-screen buttons via the real GPIOs. Host-tested key→LCD path (`tests/test_hmi_panel.py`). The factory SPI1 panel protocol is still undecoded (`docs/16`); this clean, observable panel stands in until then (see [`docs/27-hmi-emulator-app.md`](docs/27-hmi-emulator-app.md))
- [ ] Reimplement remaining modules (settings store/persistence, metering, mode state machine, faults)
- [x] Decode the inter-processor link framing → same EG4 Modbus family, with undocumented commands `0x21/0x22/0x23` (see [`docs/05-dsp-link.md`](docs/05-dsp-link.md))
- [~] Map UARTs→peers (DSP/BMS/meter/MPPT/dongle) — **dongle=UART5, DSP=USART3 (SCI-B), USART2=redundant/safety CPU, BMS=CAN1 confirmed**; meter/MPPT/console (USART1/UART4) still open. The external dongle's own firmware (ESP32-C3 RS-485 **master** datalogger) pins the dongle to **UART5** and rules out USART3 ([`docs/26`](docs/26-dongle-firmware.md)). **USART2's peer is the safety CPU** (the ARM reports E027 straight out of its frame; [`docs/30`](docs/30-safety-cpu-arm-handoff.md)); its telemetry bank format + dongle exposure are mapped in [`docs/33`](docs/33-usart2-telemetry-bank.md), and the FW-version registers (which chip each is) in [`docs/32`](docs/32-firmware-version-registers.md)
- [ ] Decode the `0x21/0x22/0x23` payloads; populate live telemetry from the DSP link
- [x] **Disassemble the TI C28x control DSP** → Ghidra 12.1.2 + `ghidra-tms320c28x` SLEIGH module; F2837x-class, image byte-swapped, ~650 functions recovered. First decode: the **"AC First" output-priority logic** (see [`docs/07-dsp-ac-first-mode.md`](docs/07-dsp-ac-first-mode.md))
- [x] **ARM→DSP config protocol** → direction + framing resolved from the DSP side: ARM **pushes all settings** as 9 positionally-packed blocks (not Modbus register writes, not deltas); DSP is the reactive slave (see [`docs/08-arm-dsp-config-protocol.md`](docs/08-arm-dsp-config-protocol.md))
- [x] **DSP config field map** → byte-exact layout `FUN_00092EE2` unpacks (per-block offsets, widths, big-endian order, DSP RAM targets) for the ARM packer; output priority = byte at frame offset `0x1E` (see [`docs/10-dsp-config-field-map.md`](docs/10-dsp-config-field-map.md))
- [x] **ARM↔DSP link = type-1 block protocol (both ends proven)** → on the ARM 260214 image, `FUN_080273b4`/`FUN_08026830` build the frame (`[0]=0x41`,`[1]=1`,`[3]=0x36`, block-id @ `0x14`, big-endian values @ `0x15`, block-id rotated to push the full set) and `FUN_08025ab8(0x14)` parses it — the exact mirror of the DSP's `FUN_00092EE2`. Not a func-3/SN Modbus response (that's a separate channel). Resolves [`docs/17`](docs/17-dsp-frame-probe-handoff.md); details in [`docs/10`](docs/10-dsp-config-field-map.md)
- [x] **AC-First GPIO-relay theory tested** → the ARM does **not** toggle a relay from the AC-First window decision; its window-active signal ends in telemetry (two static enumerations agree) and the actual power routing is DSP-side. Dynamic GPIO-capture probe committed (`tools/emu_gpio_acfirst.py`), pending the ARM image (see [`docs/14-arm-gpio-relay-acfirst.md`](docs/14-arm-gpio-relay-acfirst.md))
- [x] **ARM GPIO / IO map recovered** → all 54 configured pins on the `ceaa-07xx` image mapped to direction/mode (proven) + driver; peripherals (5 UARTs, CAN1/BMS, SPI1, TIM1 fan PWM), keys, comms-direction pins and power-path relays identified; tooling auto-detects the StdPeriph GPIO helpers (see [`docs/16-arm-io-map.md`](docs/16-arm-io-map.md), `tools/gpio_map.py`, `tools/periph_map.py`)
- [x] **Power-path relays analysed** → the 6 relay pins driven by 4 logic functions, gated chiefly by the live operating mode **IR_STATE (reg 0)** (value-matched to `states.h`) + DSP grid/EPS status, with an AutoTest/manual override; named functionally (grid/EPS transfer pair, run-enable/bypass, slow gen/AC-couple, EPS/dry-contact) with influencing registers (see [`docs/18-power-path-relays.md`](docs/18-power-path-relays.md), `tools/disres.py`)
- [x] **GPIO behaviour-test harness + first parity test** → one Unicorn emulator (`tools/arm_sim.py`) runs **both** our firmware and the factory image, instrumenting the docs/16 GPIOs. The first test (`test_pb7_input_drives_output`) is a **black box**: it injects a GPIO input, lets each firmware's *own event loop* run (`run_reset`, vector base auto-detected), and asserts the GPIO output — no entry point named, so factory and ours are indistinguishable to the test. PB7 held high → PB7 driven high, identically on both; our `pb7_sample_poll()` was TDD'd against the factory `sub_0802e452`. `make test-sim`, see [`docs/19-gpio-test-harness.md`](docs/19-gpio-test-harness.md)
- [x] **Relay parity tests + harness depth** → the harness now boots the factory through its full init (M4-core model, oscillator/RTC ready-flags, a modelled SPI NOR config flash, SysTick injection). Discovered the factory runs a **preemptive RTOS** (PendSV context switch). Two relay **parity tests** validate the factory's real relay-drive code against our `src/relay.c` (TDD'd to match): the **run-enable relay PC6 follows the operating mode** (`IR_STATE`: closed when running, open in standby/fault/programming), and the **manual/AutoTest override** drives the transfer relays (PA12←bit1, PB3←bit0). A **Cortex-M exception engine** (`arm_sim.enable_rtos()`) now models exception entry/return + SysTick + PendSV on top of Unicorn's MSP/PSP banking and context-switches to real PSP tasks — the remaining blocker to running the relay *task* through the scheduler is firmware init creating that task (config-flash contents / DSP link), not the engine (see [`docs/19`](docs/19-gpio-test-harness.md))
- [x] **ARM→DSP config push implemented** → frame builder + CRC + 8-block full-snapshot scheduler, bound to the register model; trigger confirmed as a periodic scheduler tick (continuous, not edit-driven). Host-tested (`src/dsp/`, `make test`). Block payloads 1–7 are editable field-table stubs pending field decode
- [x] **Settings persistence + clock ownership** → the DSP has **no** NV settings storage (no SPI flash / I2C EEPROM / EMIF; internal flash is update-only) and **no** power-off-surviving RTC; the ARM persists settings + owns the clock and re-provisions the DSP each boot (see [`docs/09-dsp-persistence-and-clock.md`](docs/09-dsp-persistence-and-clock.md))
- [x] **DSP 12000XP vs 18kPV** → DSP-side comparison of the two control-DSP images: same C28x/F2837x family, byte-swap, sector-0 `0x21/0x22/0x23` handler, SCI-B link and AC-First `==2`+enable-bit gating; the 18kPV is ~1.9× larger, uses 3 SCI ports, and has an entirely different RAM map (only 4.9% same-address identity) — separate builds, addresses don't transfer (see [`docs/15-dsp-12000xp-vs-18kpv.md`](docs/15-dsp-12000xp-vs-18kpv.md))
- [x] **Battery BMS image characterized (far end of CAN1)** → the attached `BATT_IN280-Z03T13.bin` is the pack's BMS, on a **Huada HC32F460-class** MCU (not STM32), flat **App @ `0x20000`** over a bootloader; BMS task set (`BmsTimer`, `DSGMosSwitchTimer`, CAN + RS485 links), model `EG4-LL`. Recovered the **CAN link contract**: 8 selectable inverter-brand presets incl. **`P07-LUX`** (Luxpower = our inverter), and the standard-11-bit TX frame table (`0x351/0x355/0x356/0x359/0x35x`) at `0x31a20`. **Per-frame byte layout recovered** from the builder `FUN_0002a0bc` — 16-byte descriptor records, byte-exact `0x351`/`0x355`/`0x356` fields (charge/discharge limits, SOC/SOH, V/I/T) in the standard little-endian preset (a second preset path packs big-endian), plus the RX IDs `0x300/0x301/0x305/0x400`; captured in [`include/inv/bms_can_map.h`](include/inv/bms_can_map.h). Baud (expect 500k) + alarm-bit map pending (see [`docs/20-battery-bms-firmware.md`](docs/20-battery-bms-firmware.md), `tools/batt_canmap.py --builders`)
- [x] **Factory-coverage dashboard** → a long-term metric for how much of the factory firmware our parity tests actually exercise: the harness records every factory basic block executed while the `test-sim` tests run against the factory image, mapped onto the recovered function map (`reference/symbols.csv`). The factory's HMI/display code is found from the image itself (`tools/hmi_classify.py` → `reference/hmi_functions.csv`, call-graph closure from the menu/string roots) and ignored — but only where the functional tests never execute it, so the ignore set shrinks as the suite grows. `make coverage` regenerates the checked-in [`docs/factory-coverage.md`](docs/factory-coverage.md) — headline + instruction-weighted %, per-module table, and a ranked worklist of the biggest unexercised functions (see [`docs/37-factory-coverage.md`](docs/37-factory-coverage.md))
- [x] **Firmware-update / bootloader entry** → the dongle is only a conduit; updates rely on the ARM cooperating. For the DSP/peers the ARM is the flashing *master* (`0x21/0x22/0x23` "EDSN", [`docs/05`](docs/05-dsp-link.md)); for its own update the ARM reboots itself into its bootloader on the dongle's `ResetSetting.InvReboot` command (holding reg 11 bit 7 → `NVIC_SystemReset` → bootloader at `0x08000000`). Parity test by shared contract (`ArmSim.watch_system_reset()`): our firmware black-box on the real Modbus command, the factory by its reset site — both must request the reset into the bootloader (see [`docs/38-firmware-update-bootloader.md`](docs/38-firmware-update-bootloader.md))
- [ ] Verify on hardware

## The honest scope

Reimplementing shipped firmware from a binary is a substantial,
multi-contributor effort — expect it measured in months, not days. The binary
is readable (good), but the *meaning* of its numbers (enum values, scaling,
storage layout, and especially the DSP protocol) must be recovered piece by
piece. This repo is structured so that work parallelizes and accumulates.

## Strategy

We treat the original binary as a **specification oracle**, not source to copy:

1. **Build for the real chip first.** An `arm-none-eabi-gcc` + CMSIS skeleton
   with our own linker script (STM32F103, boot at `0x08000000`) that compiles
   to a flashable `.bin`. First milestone: it boots and drives the LCD/keys.
2. **Reimplement behavior module by module**, using the original binary and a
   live unit to define correct behavior. Start with the safe, observable parts
   (HMI, menus, telemetry display), then the mode state machine, then comms.
3. **The DSP link is the contract.** Reproduce the ARM↔DSP protocol exactly;
   everything else can be rewritten freely as long as that interface holds.

Output is **functionally** equivalent, not byte-identical (the original was
built with Keil armcc + scatter-loading; we use GCC). Byte-matching is an
explicit non-goal.

## Building

```bash
make                 # EG4 12000XP (monolithic image, vectors @0x08000000)
make VARIANT=18kpv   # EG4 18kPV   (App over ~50 KB bootloader, vectors @0x0800C800)
make VARIANT=6000xp  # EG4 6000XP  (App over ~20 KB bootloader, vectors @0x08005000)
make test            # host-side unit tests (no hardware)
make test-sim        # GPIO/HMI behaviour tests on the Unicorn harness
make coverage        # regenerate docs/factory-coverage.md (needs the factory image)
make hmi             # interactive on-screen HMI (LCD + keys) in a browser
make hmi-sim         # graphic-HMI simulator (open build; FIRMWARE=App.hex for a vendor image)
make factory-hmi     # the simulator on the factory image specifically (docs/28)
```

`make hmi` boots the firmware in the emulator and serves its HMI — a 20×4
character LCD plus the four front-panel keys — at `http://localhost:8080/`
(`PORT=…` to change). Every keypress drives the real key GPIOs; the firmware
renders the new screen over I²C to a modelled LCD. See
[`docs/27-hmi-emulator-app.md`](docs/27-hmi-emulator-app.md). Needs
`pip install unicorn`.

`VARIANT` selects the linker script (`ldscripts/stm32f103ve.ld` vs
`ldscripts/stm32f103_18kpv_app.ld`) and defines the active variant; both model
descriptors are always linked in. Flash to the variant's base: `0x08000000`
(12000XP) or `0x0800C800` (18kPV App — the bootloader below is not ours).

Requires `gcc-arm-none-eabi` (build) and a host `cc` (tests). The firmware boots,
runs the 72 MHz clock init, starts a 1 ms SysTick, and services a Modbus-RTU
slave against a shared register model — the foundation the remaining
subsystems grow into, not yet a functional replacement. (The slave is bound to
USART3 in the skeleton; in the factory the external dongle's EG4-Modbus is on
**UART5** while USART3 is the ARM↔DSP link — [`docs/26`](docs/26-dongle-firmware.md).) Flashing helpers
(ST-Link / OpenOCD) are commented in the `Makefile`; flash to `0x08000000`.

## Repository layout

```
docs/        analysis + recovered specification (start here)
docs/wiring/ per-link wiring source-of-truth (ports, pins, peers, framing)
include/     stm32f103.h (minimal device header) + inv/ recovered data model
include/inv/ states, faults, settings, modbus_map, hmi_menu, variant
src/         startup_stm32f103.c, system_stm32f103.c, variant.c, main.c (skeleton)
src/modbus/  Modbus-RTU slave engine + USART3 port
src/uart/    interrupt-driven USART3 driver (RX/TX rings)
src/can/     CAN1 port (polled RX, as the factory) + BMS frame decoder
src/hmi/     LCD/keypad menu engine + menu model + port (I²C 20×4 HD44780)
src/dsp/     ARM->DSP config push (8-block full-snapshot protocol)
ldscripts/   stm32f103ve.ld (12000XP) + *_18kpv_app.ld + *_6kxp_app.ld (App builds)
tests/       host unit tests (make test)
tools/       RE scripts (read-only) + the Unicorn emulator & on-screen HMI app
reference/   original .bin (gitignored) + generated RE outputs (symbols*.csv, …)
Makefile     build -> flashable .bin ; make test
```

## The original binaries are not committed

The proprietary factory images are **not** part of this repository. Contributors
place their own copy under `reference/` (gitignored). Recorded for integrity:

| File | size | md5 |
|---|---|---|
| `..._com_vE_250325.bin` (12000XP ARM, this project) | 244080 | `d1c1d8dedd26d59518e95668e95f06d6` |
| `..._dsp_vE_250325.bin` (12000XP TI DSP, out of scope) | 141304 | `4e3e360ed21742275c2885cba8b69724` |
| `..._ceaa-05xx_com_vE_250325.hex` (12000XP ARM, 05-series) | 587465 | `d07b6b5ddfdcddd453a3b0cc845e9659` |
| `..._ceaa-07xx_vE_260214_Br7k5_2.hex` (12000XP ARM, 07-series App) | 574885 | `ccc5172a11ea1e1b302c83bc8e834846` |
| `..._FAAB-1Bxx_20240528_App.hex` (18kPV ARM App) | 502737 | `7091e1ad60fa2e725a5da8d39fa5bc8c` |
| `..._ccaa-xx15xx_260519.hex` (6000XP ARM App) | 478004 | `220f1a2fd8aa6adbdbb0a2bea6b9880d` |
| `169a5158-CBAA-1Cxxxx_mppt_250805.hex` (MPPT stage controller, STM32G0-class Cortex-M0+ — separate processor) | 104767 | `9c4168c1f1ac42cdd0ab6e01deb77325` |

As the product's maintainer you own these images; whether/how to publish them is
your call. Keeping them out of the public tree is the conventional default.

## Contributing

Pick an unchecked box above or an "unknown" row in
[`docs/02-recovered-model.md`](docs/02-recovered-model.md). The most valuable
early contributions are (a) the exact MCU part number, (b) the ARM↔DSP protocol,
and (c) a config dump + Modbus map from a real unit.

## License

**GNU GPL v3.0** — see [`LICENSE`](LICENSE). Contributions are accepted under
the same license.
