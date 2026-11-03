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
- [ ] Pointer-table resolver → recover the HMI **menu tree** and auto-name functions
- [ ] Document the **ARM↔DSP internal protocol** (the remaining hard interface)
- [ ] Buildable skeleton: linker script + startup + CMSIS that compiles to a `.bin` for the real chip
- [ ] Reimplement modules (Modbus slave, HMI, settings store, metering, mode state machine, faults)
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

## Repository layout

```
docs/        analysis + recovered specification (start here)
include/inv/ recovered data model as C headers (states, faults, settings, modbus_map)
tools/       reverse-engineering scripts (read-only, operate on the .bin)
src/         reimplementation source (skeleton — TBD)
ldscripts/   linker script(s) for the rebuild (TBD)
reference/   original .bin (gitignored) + generated RE outputs (symbols.csv, …)
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

TBD by the maintainer. An open reimplementation intended for community
contribution typically uses a permissive (MIT/Apache-2.0) or copyleft (GPLv3)
license — pick before the first external contribution.
