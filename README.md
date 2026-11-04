# inverter-com-fw — open-source firmware for the inverter's ARM "com" MCU

An open, C-language reimplementation of the **communications / HMI / supervisor**
firmware (the ARM Cortex-M "com" processor) of EG4 all-in-one solar off-grid
inverters. The goal is a codebase the community can read, build, flash, and
extend with new features.

**Supported variants: EG4 12000XP, EG4 18kPV, and EG4 6000XP.**
Reverse-engineering the factory ARM images proves they are the **same codebase**
on the **same MCU** (STM32F103 high-density, Cortex-M3), differing only in a
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
smaller STM32F103, newly characterized — see
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

- [x] Confirm target MCU and memory map → **STM32F103 high-density, Cortex-M3**, flash `0x08000000`, RAM `0x20000000` (see [`docs/01-firmware-analysis.md`](docs/01-firmware-analysis.md))
- [x] Confirm the image is **not encrypted/compressed** (reimplementation is feasible)
- [x] Identify the product → **EG4 12000XP** (Modbus spec shared with the 18kPV-12LV superset)
- [x] **Add a second variant → EG4 18kPV** (3 MPPT, hybrid): proved same MCU + codebase from the factory `App.hex`; captured the deltas as a build-selectable variant descriptor (see [`docs/10-18kpv-vs-12000xp.md`](docs/10-18kpv-vs-12000xp.md), `include/inv/variant.h`, `make VARIANT=18kpv`)
- [x] **Track 12000XP revisions over time** → `ceaa-05xx` (2025-03) vs `ceaa-07xx` (2026-02): the 07 series moved to a **bootloader + App** layout (vectors relocated `0x08000000`→`0x08005000`), and added generator scheduling / quick-charge / smart-load / resume-SOC / buzzer menus — mapped to the vendor changelog (see [`docs/11-12000xp-revisions.md`](docs/11-12000xp-revisions.md))
- [x] **Add a third variant → EG4 6000XP** (`ccaa`): same MCU + codebase (07-era), same bootloader + App layout as the 12000XP 07-series (vectors @`0x08005000`, 20 KB bootloader); added as a build target `make VARIANT=6000xp` (see [`docs/12-6000xp.md`](docs/12-6000xp.md))
- [x] **Identify a distinct `mppt` power-stage controller image** (`CBAA`): *not* a com-MCU variant — a smaller **STM32F103xB (128 KB)** running a bare-metal **TIM1-PWM + ADC + DMA** control loop (zero HMI strings, only TIM1_CC + EXTI3 interrupts), built with the same EG4 toolchain/boot conventions. A separate peer processor for the solar DC-DC stage (see [`docs/13-mppt-controller.md`](docs/13-mppt-controller.md))
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
- [x] **Modbus-RTU slave** — engine + USART3 port + host tests (`make test`, see [`docs/04-modbus.md`](docs/04-modbus.md))
- [x] **HMI menu system** — data-driven menu engine + model + host-tested navigation (see [`docs/06-hmi.md`](docs/06-hmi.md))
- [ ] Reimplement remaining modules (settings store/persistence, metering, mode state machine, faults)
- [x] Decode the inter-processor link framing → same EG4 Modbus family, with undocumented commands `0x21/0x22/0x23` (see [`docs/05-dsp-link.md`](docs/05-dsp-link.md))
- [ ] Map UARTs→peers (DSP/BMS/meter/MPPT/dongle) — needs schematic or data-flow trace
- [ ] Decode the `0x21/0x22/0x23` payloads; populate live telemetry from the DSP link
- [x] **Disassemble the TI C28x control DSP** → Ghidra 12.1.2 + `ghidra-tms320c28x` SLEIGH module; F2837x-class, image byte-swapped, ~650 functions recovered. First decode: the **"AC First" output-priority logic** (see [`docs/07-dsp-ac-first-mode.md`](docs/07-dsp-ac-first-mode.md))
- [x] **ARM→DSP config protocol** → direction + framing resolved from the DSP side: ARM **pushes all settings** as 9 positionally-packed blocks (not Modbus register writes, not deltas); DSP is the reactive slave (see [`docs/08-arm-dsp-config-protocol.md`](docs/08-arm-dsp-config-protocol.md))
- [x] **DSP config field map** → byte-exact layout `FUN_00092EE2` unpacks (per-block offsets, widths, big-endian order, DSP RAM targets) for the ARM packer; output priority = byte at frame offset `0x1E` (see [`docs/10-dsp-config-field-map.md`](docs/10-dsp-config-field-map.md))
- [x] **ARM↔DSP link = type-1 block protocol (both ends proven)** → on the ARM 260214 image, `FUN_080273b4`/`FUN_08026830` build the frame (`[0]=0x41`,`[1]=1`,`[3]=0x36`, block-id @ `0x14`, big-endian values @ `0x15`, block-id rotated to push the full set) and `FUN_08025ab8(0x14)` parses it — the exact mirror of the DSP's `FUN_00092EE2`. Not a func-3/SN Modbus response (that's a separate channel). Resolves [`docs/17`](docs/17-dsp-frame-probe-handoff.md); details in [`docs/10`](docs/10-dsp-config-field-map.md)
- [x] **AC-First GPIO-relay theory tested** → the ARM does **not** toggle a relay from the AC-First window decision; its window-active signal ends in telemetry (two static enumerations agree) and the actual power routing is DSP-side. Dynamic GPIO-capture probe committed (`tools/emu_gpio_acfirst.py`), pending the ARM image (see [`docs/14-arm-gpio-relay-acfirst.md`](docs/14-arm-gpio-relay-acfirst.md))
- [x] **ARM GPIO / IO map recovered** → all 54 configured pins on the `ceaa-07xx` image mapped to direction/mode (proven) + driver; peripherals (5 UARTs, CAN1/BMS, SPI1, TIM1 fan PWM), keys, comms-direction pins and power-path relays identified; tooling auto-detects the StdPeriph GPIO helpers (see [`docs/16-arm-io-map.md`](docs/16-arm-io-map.md), `tools/gpio_map.py`, `tools/periph_map.py`)
- [x] **Power-path relays analysed** → the 6 relay pins driven by 4 logic functions, gated chiefly by the live operating mode **IR_STATE (reg 0)** (value-matched to `states.h`) + DSP grid/EPS status, with an AutoTest/manual override; named functionally (grid/EPS transfer pair, run-enable/bypass, slow gen/AC-couple, EPS/dry-contact) with influencing registers (see [`docs/18-power-path-relays.md`](docs/18-power-path-relays.md), `tools/disres.py`)
- [x] **GPIO behaviour-test harness** → one Unicorn emulator (`tools/arm_sim.py`) runs **both** our firmware and the factory image, instrumenting the docs/16 GPIOs (set_input/get_output/call/run_reset); first end-to-end test proves a factory input→output base case (PB7 sampled → PB7 driven) and that our firmware boots and configures its USART3 pins. `make test-sim`, see [`docs/19-gpio-test-harness.md`](docs/19-gpio-test-harness.md)
- [x] **ARM→DSP config push implemented** → frame builder + CRC + 8-block full-snapshot scheduler, bound to the register model; trigger confirmed as a periodic scheduler tick (continuous, not edit-driven). Host-tested (`src/dsp/`, `make test`). Block payloads 1–7 are editable field-table stubs pending field decode
- [x] **Settings persistence + clock ownership** → the DSP has **no** NV settings storage (no SPI flash / I2C EEPROM / EMIF; internal flash is update-only) and **no** power-off-surviving RTC; the ARM persists settings + owns the clock and re-provisions the DSP each boot (see [`docs/09-dsp-persistence-and-clock.md`](docs/09-dsp-persistence-and-clock.md))
- [x] **DSP 12000XP vs 18kPV** → DSP-side comparison of the two control-DSP images: same C28x/F2837x family, byte-swap, sector-0 `0x21/0x22/0x23` handler, SCI-B link and AC-First `==2`+enable-bit gating; the 18kPV is ~1.9× larger, uses 3 SCI ports, and has an entirely different RAM map (only 4.9% same-address identity) — separate builds, addresses don't transfer (see [`docs/15-dsp-12000xp-vs-18kpv.md`](docs/15-dsp-12000xp-vs-18kpv.md))
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
```

`VARIANT` selects the linker script (`ldscripts/stm32f103ve.ld` vs
`ldscripts/stm32f103_18kpv_app.ld`) and defines the active variant; both model
descriptors are always linked in. Flash to the variant's base: `0x08000000`
(12000XP) or `0x0800C800` (18kPV App — the bootloader below is not ours).

Requires `gcc-arm-none-eabi` (build) and a host `cc` (tests). The firmware boots,
runs the 72 MHz clock init, starts a 1 ms SysTick, and services a Modbus-RTU
slave over USART3 against a shared register model — the foundation the remaining
subsystems grow into, not yet a functional replacement. Flashing helpers
(ST-Link / OpenOCD) are commented in the `Makefile`; flash to `0x08000000`.

## Repository layout

```
docs/        analysis + recovered specification (start here)
include/     stm32f103.h (minimal device header) + inv/ recovered data model
include/inv/ states, faults, settings, modbus_map, hmi_menu, variant
src/         startup_stm32f103.c, system_stm32f103.c, variant.c, main.c (skeleton)
src/modbus/  Modbus-RTU slave engine + USART3 port
src/hmi/     LCD/keypad menu engine + menu model + port
src/dsp/     ARM->DSP config push (8-block full-snapshot protocol)
ldscripts/   stm32f103ve.ld (12000XP) + *_18kpv_app.ld + *_6kxp_app.ld (App builds)
tests/       host unit tests (make test)
tools/       reverse-engineering scripts (read-only, operate on the .bin)
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
| `169a5158-CBAA-1Cxxxx_mppt_250805.hex` (MPPT stage controller, STM32F103xB — separate processor) | 104767 | `9c4168c1f1ac42cdd0ab6e01deb77325` |

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
