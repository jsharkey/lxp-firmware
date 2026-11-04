# inverter-com-fw — open-source firmware for the inverter's ARM "com" MCU

An open, C-language reimplementation of the **communications / HMI / supervisor**
firmware (the ARM Cortex-M "com" processor) of the **EG4 12000XP** all-in-one
solar off-grid inverter. The goal is a codebase the community can read, build,
flash, and extend with new features.

> The firmware is the **12000XP**; the Modbus spec on hand is the closely related
> **18kPV-12LV** (same protocol, a superset). The 12000XP is non-hybrid with
> 2 MPPTs, so some registers/features in the map are unused here. The com-MCU
> codebase appears shared across EG4 models, variant-selected by the `Model`
> setting.

The device has **three processors**: a TI C2000 **Control DSP**, this STM32
**Communication/HMI MCU** (what this project reimplements), and a **redundant
safety CPU**. We reimplement only the Communication MCU.

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
- [x] **ARM→DSP config protocol** → direction + framing resolved from the DSP side: ARM **pushes all settings** as 8 positionally-packed blocks (not Modbus register writes, not deltas); DSP is the reactive slave (see [`docs/08-arm-dsp-config-protocol.md`](docs/08-arm-dsp-config-protocol.md))
- [x] **ARM→DSP config push implemented** → frame builder + CRC + 8-block full-snapshot scheduler, bound to the register model; trigger confirmed as a periodic scheduler tick (continuous, not edit-driven). Host-tested (`src/dsp/`, `make test`). Block payloads 1–7 are editable field-table stubs pending field decode
- [x] **Settings persistence + clock ownership** → the DSP has **no** NV settings storage (no SPI flash / I2C EEPROM / EMIF; internal flash is update-only) and **no** power-off-surviving RTC; the ARM persists settings + owns the clock and re-provisions the DSP each boot (see [`docs/09-dsp-persistence-and-clock.md`](docs/09-dsp-persistence-and-clock.md))
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
make            # -> build/firmware.{elf,bin,hex} + size report
make test       # host-side unit tests (no hardware) — currently the Modbus engine
```

Requires `gcc-arm-none-eabi` (build) and a host `cc` (tests). The firmware boots,
runs the 72 MHz clock init, starts a 1 ms SysTick, and services a Modbus-RTU
slave over USART3 against a shared register model — the foundation the remaining
subsystems grow into, not yet a functional replacement. Flashing helpers
(ST-Link / OpenOCD) are commented in the `Makefile`; flash to `0x08000000`.

## Repository layout

```
docs/        analysis + recovered specification (start here)
include/     stm32f103.h (minimal device header) + inv/ recovered data model
include/inv/ states, faults, settings, modbus_map, hmi_menu
src/         startup_stm32f103.c, system_stm32f103.c, main.c (skeleton)
src/modbus/  Modbus-RTU slave engine + USART3 port
src/hmi/     LCD/keypad menu engine + menu model + port
src/dsp/     ARM->DSP config push (8-block full-snapshot protocol)
ldscripts/   stm32f103ve.ld linker script
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
| `..._com_vE_250325.bin` (ARM, this project) | 244080 | `d1c1d8dedd26d59518e95668e95f06d6` |
| `..._dsp_vE_250325.bin` (TI DSP, out of scope) | 141304 | `4e3e360ed21742275c2885cba8b69724` |

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
