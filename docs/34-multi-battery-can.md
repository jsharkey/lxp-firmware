# Multi-battery telemetry on the single CAN link — and CAN firmware update

Does the one CAN cable to the "master" battery carry details for the *other*
stacked packs (per-pack ID, firmware rev, voltage, SOC/SOH, DC current, min/max
cell temp/voltage), and does it reach the dongle Modbus? And can the battery be
**flash-updated over CAN**?

Short answers, from static RE of both ends plus harness probes:

1. **Yes — the master emits per-pack + extended-stack telemetry frames** over
   the single CAN bus (beyond the aggregate `0x351/0x355/0x356/0x359/…` we
   already flow). The frame *ranges* are confirmed in the battery image.
2. **But this inverter firmware does not surface them on the dongle Modbus.**
   The ARM receives and buffers the extended frames in RAM, yet publishes none of
   them to an input/holding register — confirmed three independent ways. So the
   per-pack data is *on the wire* but the `ceaa-07xx` inverter **aggregates to one
   logical pack** for the dongle.
3. **Firmware-update-over-CAN is plausible and the primitives are present** (the
   battery self-programs flash and can reset to its bootloader), but the CAN-IAP
   protocol itself lives in the bootloader partition, which is **not in the App
   blob we have**, so this is strong circumstantial — not byte-level — evidence.

Sources: battery App `reference/BATT_IN280-Z03T13.bin` (HC32F460, flat App @
`0x00020000`; proprietary, gitignored) via `tools/batt_canmap.py` + Thumb
disassembly; factory ARM `reference/com_flat.bin` via `tools/arm_sim.py` probes;
the dongle register surface in [`docs/modbus-dongle/`](modbus-dongle/README.md)
and [`docs/33`](33-usart2-telemetry-bank.md); battery basics in
[`docs/20`](20-battery-bms-firmware.md).

## 1. The master emits per-pack + extended frames (battery side)

The battery's CAN TX descriptor table (`@0x00031a20`, 55 entries of
`{u32 id; u32 dlc; u8 data[8]}`) carries, besides the aggregate core set, two
extended ranges — exactly the SMA/Victron/Pylontech "CAN bus battery" family's
multi-pack + stack-detail frames:

| frames | role (protocol family) |
|---|---|
| `0x311`–`0x321` (17 IDs) | **per-pack** telemetry (one block per attached battery) |
| `0x370`–`0x381` (18 IDs) | **extended stack detail**: module counts, min/max **cell voltage** & **cell temperature**, installed capacity, SW/HW **version**, **serial** |
| `0x35e` | manufacturer name (`"EG4/LUX"` — in-band at `0x31afc`) |
| `0x35f` | **firmware / capacity** info (builder at `0x0002c92a`) |

So the user's wish-list — per-battery **ID**, **firmware rev**, total **voltage**,
**SOC/SOH**, **DC current**, **min/max cell temp/voltage** — maps onto
`0x311–0x321` (per-pack core) + `0x370–0x381` (cell/version/serial) + `0x35e/0x35f`
(identity/firmware). The ranges are confirmed; the exact per-frame byte layout is
assembled by the ~3,900-instruction table-driven builder `FUN_0002a0bc` and is
**not fully byte-mapped here** (the aggregate `0x351/0x355/0x356/0x359` layouts
are, in [`docs/20`](20-battery-bms-firmware.md) and `include/inv/bms_can_map.h`).
The battery also stacks internally over **RS485 with auto-addressing** (docs/20) —
that daisy-chain is how the master gathers the other packs before forwarding them
on CAN, which is the mechanism behind "one cable, many packs."

## 2. The inverter buffers them but exposes none on the dongle

Three independent checks on the `ceaa-07xx` ARM image all agree: the extended
frames are **received and buffered** but **not published to any Modbus register**.

- **Harness injection → no register moves.** Injecting all of `0x370–0x381` and
  `0x311–0x321` (and, with realistic values, the cell-detail frame `0x373` and
  capacity/module-count `0x379`/`0x372`) through `CanBattery`, then sweeping
  **every input register 0–239** over the dongle, changes **nothing** — whereas
  the aggregate frames populate IR 4/5/98/99/100/103/96 as documented
  ([`docs/20`](20-battery-bms-firmware.md)).
- **They land in a raw CAN buffer, not the register image.** The injected bytes
  *do* appear in RAM around `0x20008000`+ (e.g. a `0x373` frame at
  `0x2000_802b`), but at **byte-misaligned** offsets — a raw frame staging buffer,
  not the aligned u16 register image at `0x2000_d7xx` that the Modbus getters
  serve. So the parser ingests them; nothing copies them to a register.
- **The authoritative register surface has no per-pack slots.** The dongle's
  per-register docs ([`docs/modbus-dongle/`](modbus-dongle/README.md)) and the
  USART2-bank→register sweep ([`docs/33`](33-usart2-telemetry-bank.md)) list a
  **single aggregate BMS block** (IR 81–106) and nothing per-battery; the input
  map tops out around IR 152.

**Conclusion.** The per-battery data genuinely crosses the single CAN link and
reaches the inverter's RAM, but the `ceaa-07xx` firmware **aggregates to one
logical battery** for the dongle Modbus — there is no per-pack register bank on
this image. If an EG4 tool shows per-pack detail, it is via another channel (the
battery's own RS485/BLE, or a newer inverter build), not these Modbus registers.
*(This also explains quirk Q1 in [`docs/31`](31-factory-quirks.md): with the real
max-cell-voltage frame `0x373` never wired to IR 101, the `0x355` high-res SOC
field bleeds into that slot.)*

> For **our** open firmware this is a design choice, not a contract to match:
> there is no factory oracle for per-pack registers, so a common harness test
> can't pin one. If we want per-pack visibility we'd *extend* beyond the factory
> (decode `0x311–0x321`/`0x370–0x381`, define our own register bank) — a
> deliberate superset, flagged as such.

## 3. Firmware update over CAN (extra credit)

The battery is a **two-stage** design: a bootloader occupies `0x0`–`0x20000`
with the App above it (docs/20), and the Keil build links the HC32 **EFM
embedded-flash** driver (`hc32_ll_efm.c`). Evidence the running App has the
field-update primitives:

- **Self-programs flash.** `EFM 0x40010400` is referenced at `0x20ed4`,
  `0x252e4`, `0x2536c`; the write path issues the EFM **unlock-key sequence**
  (`0x77` → the `FAPRT` protect register, twice) before programming — real
  erase/program, not a status read.
- **Can reset to the bootloader.** `SCB->AIRCR` (`0xE000ED0C`) is referenced at
  `0x272bc`/`0x31554`; the reset site is the textbook `NVIC_SystemReset` (write
  AIRCR, `DSB`, spin) — the mechanism a "enter update mode" command uses.
- **Has an inverter→battery command channel.** The RX dispatcher `FUN_0002314c`
  decodes `0x301` (config, 8-byte copy) and `0x400` (command) off CAN — the path
  by which an update/enter-bootloader request would arrive.

What's **not** provable from this blob: the actual "receive firmware chunks over
CAN and write them" loop. That is the **bootloader's** job (standard for these
BMS — the App jumps to the bootloader, which runs the CAN IAP), and the
bootloader partition (`0x0`–`0x20000`) is **not** in the App image we have. So:
field-update over CAN is well-supported by the design (two-stage + EFM
self-programming + reset + CAN command channel), but byte-level proof of the CAN
flashing protocol needs the bootloader dump.

## Reproduce

```bash
python3 tools/batt_canmap.py reference/BATT_IN280-Z03T13.bin --builders   # TX frame table
# ARM-side: inject extended frames, sweep registers (see the probe in this note's history)
```
