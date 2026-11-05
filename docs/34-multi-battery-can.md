# Multi-battery telemetry on the single CAN link — and CAN firmware update

Does the one CAN cable to the "master" battery carry details for the *other*
stacked packs (per-pack ID, firmware rev, voltage, SOC/SOH, DC current, min/max
cell temp/voltage), and does it reach the dongle Modbus? And can the battery be
**flash-updated over CAN**?

Short answers, from static RE of both ends plus harness probes:

1. **Yes — the master emits per-pack + extended-stack telemetry frames** over
   the single CAN bus (beyond the aggregate `0x351/0x355/0x356/0x359/…` we
   already flow). The frame *ranges* are confirmed in the battery image.
2. **CORRECTED — they ARE surfaced, on an undocumented high register range
   (input registers 5000–5126).** This note first concluded the opposite; that was
   wrong because the check swept only IR 0–239. The serializer routes input
   registers **5000–5126 to a separate getter** (`sub_08020cc0`) that serves a
   **per-pack array** (`0x2000691c`, stride `0x36`) filled from the CAN per-pack
   frames by `sub_080205d4`. A harness probe injecting per-pack frames and reading
   5000+ over the dongle returns the per-pack values (while IR 0–239 stays blank —
   which is why the first sweep missed it). Full mechanism + proof in
   **[§2b](#2b-correction--per-pack-data-is-surfaced-on-undocumented-registers-50005126)**
   below. (The §2 checks that follow remain correct *as far as they go* — the
   per-pack data genuinely is not in IR 0–239 — but the conclusion drawn from them
   was not.)
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
- **The dongle end defines no per-pack registers — it is a transparent conduit.**
  Checked from the *dongle's own* firmware ([`docs/26`](26-dongle-firmware.md), the
  attached `E_V2_12` ESP32-C3 image): it carries **no inverter register map and no
  BMS-specific command** of its own. Its RS-485 layer is a generic byte pipe —
  `RS485Service` exposes `SendBytes(port, buf, len)` (+ `uart_wait_tx_done`) and a
  `UartRxTask`, shuttling **opaque** EG4-Modbus frames between its cloud/BLE side
  and the inverter; `RS485App.c` is mostly logging and queue plumbing, with **no
  on-device function-code / register dispatch**. So nothing on the dongle asks for
  — or could decode — a per-pack bank; it relays whatever (aggregate) registers
  the cloud polls and the ARM serves. (The extended `0x21/0x22/0x23` family that
  *is* a non-register path is the **DSP** bootloader/config protocol on USART3
  [`docs/05`](05-dsp-link.md)/[`docs/08`](08-arm-dsp-config-protocol.md), reached
  by the ARM as master — not something the UART5 dongle issues for BMS data.)

**Conclusion (corrected — see [§2b](#2b-correction--per-pack-data-is-surfaced-on-undocumented-registers-50005126)).**
The per-battery data genuinely crosses the single CAN link, reaches the inverter's
RAM, and **is served to the dongle Modbus** — on an **undocumented high register
bank, input registers 5000–5126** (`sub_08020cc0`, per-pack array `0x2000691c`),
fed from the CAN per-pack frames by `sub_080205d4`. It is simply **not** in the
IR 0–239 space the aggregate block lives in, which is why the first sweep here
concluded (wrongly) that nothing surfaced it. The dongle, a transparent conduit,
relays whatever registers the cloud polls — including 5000+ — so an EG4 tool that
reads the 5000 bank sees full per-pack detail over this same Modbus link.
*(This also explains quirk Q1 in [`docs/31`](31-factory-quirks.md): with the real
max-cell-voltage frame `0x373` never wired to IR 101, the `0x355` high-res SOC
field bleeds into that slot.)*

> For **our** open firmware this is a design choice, not a contract to match:
> there is no factory oracle for per-pack registers, so a common harness test
> can't pin one. If we want per-pack visibility we'd *extend* beyond the factory
> (decode `0x311–0x321`/`0x370–0x381`, define our own register bank) — a
> deliberate superset, flagged as such.

## 2b. CORRECTION — per-pack data IS surfaced, on undocumented registers 5000–5126

The §2 checks establish a true fact (the per-pack bytes are not in input registers
**0–239**) but the conclusion — "no register, documented or undocumented" — was
wrong: it assumed the served register space ends near IR 152. It does not. The
Modbus serializer `sub_0803373c` has a **third getter branch** for a high range:

```
reg < 5000  (0x1388)      -> sub_0803289c   (normal input getter, IR 0..~152)
5000 <= reg < 5127        -> sub_08020cc0   (per-pack getter)   <-- undocumented
reg >= 5127               -> sub_0803289c
```

**The per-pack getter `sub_08020cc0`** serves input registers **5000–5126** from a
per-pack telemetry array:

- base **`0x2000691c`**, **stride `0x36`** (54 bytes = 27 × u16) per pack;
- gated by a **pack-present bitmask `0x2000a770`** (bit *p* = pack *p* present) and
  a **pack-page count `0x2000a8ae`**;
- layout: **30 register slots per pack**, four pack-slots visible at a time at
  bases **5000 / 5030 / 5060 / 5090** (27 fields used of each 30), and a cycling
  page index (`0x2000a9c9`) that advances the window for **>4 packs**. So one
  dongle poll of 5000–5119 reads four packs; successive polls page through the
  rest.

**How the array is filled — `sub_080205d4`** is the per-pack CAN parser. Per-pack
frames arrive with CAN id **`0x400 | (subtype<<5) | pack_index`** (low 5 bits =
pack 0–31, bits 5–7 = subtype 0–7). For each frame it sets the pack's presence
bit (`0x2000a770`), updates the count (`0x2000a8ae`), and stores the subtype's
fields into `0x2000691c + 0x36*pack`. So the chain is:

```
CAN 0x400|sub<<5|pack  ->  sub_080205d4  ->  per-pack array 0x2000691c[pack]
                                          +  presence 0x2000a770 / count 0x2000a8ae
                                          ->  input regs 5000-5126 (sub_08020cc0)  ->  dongle
```

**Proof (harness).** Injecting per-pack frames through `CanBattery` and reading
5000+ over the dongle returns the injected per-pack values, for multiple packs,
and tracks changes — while IR 0–239 stays blank (the §2 observation). Locked in as
`test_per_pack_telemetry_reaches_modbus` (tests/test_arm_sim_factory_only.py):

```
inject id 0x400 pack0 sub0 = <0x1234,0xABCD,…>,  pack0 sub1 = <0x5678,…>,  pack1 sub0 = <0x9ABC,…>
read   IR 5000 = 0x1234   IR 5001 = 0xABCD   IR 5004 = 0x5678   IR 5030 = 0x9ABC
```

(reg 5000 = pack-0 subtype-0 bytes[0:2], 5001 = bytes[2:4], 5004 = subtype-1
bytes[0:2], 5030 = pack-1 subtype-0 bytes[0:2].)

### The full 27-field map (per pack)

Recovered byte-exact from the parser `sub_080205d4` (the per-subtype store
branches) + the getter `sub_08020cc0`, and verified in the harness. Each pack is
one **27 × u16** record (stride `0x36`); `sub_08014dc6` reads every field
**little-endian** and the parser applies **no scaling**. Register = `5000 +
30·pack_slot + field` (for the pack shown at base 5000). The named layout is
[`include/inv/perpack_map.h`](../include/inv/perpack_map.h) (`PP_S<sub>_W<word>`).

| field | reg (pack@5000) | CAN id | subtype | source bytes | note |
|---|---|---|---|---|---|
| 0  | 5000 | `0x400` | 0 | b0:1 | u16 LE |
| 1  | 5001 | `0x400` | 0 | b2:3 | u16 LE |
| 2  | 5002 | `0x400` | 0 | b4 (lo), b7 (hi) | **split pair** |
| 3  | 5003 | `0x400` | 0 | b5:6 | u16 LE |
| 4–7   | 5004–5007 | `0x420` | 1 | b0:1, b2:3, b4:5, b6:7 | u16 LE ×4 |
| 8–11  | 5008–5011 | `0x440` | 2 | b0:1, b2:3, b4:5, b6:7 | u16 LE ×4 |
| 12–15 | 5012–5015 | `0x460` | 3 | b0:1, b2:3, b4:5, b6:7 | u16 LE ×4 |
| 16–18 | 5016–5018 | `0x480` | 4 | b0:1, b2:3, b4:5 | u16 LE ×3 |
| 19–22 | 5019–5022 | `0x4A0` | 5 | b0:1, b2:3, b4:5, b6:7 | u16 LE ×4 |
| 23–25 | 5023–5025 | `0x4C0` | 6 | b0:1, b2:3, b4:5 | u16 LE ×3 |
| 26 | 5026 | `0x4C0` | 6 | b6 | u8 (hi byte 0) |

(The CAN id encodes `0x400 | subtype<<5 | pack`; subtype 7 writes none of these 27
fields. The pack index is 5 bits, so up to 32 packs page through 5000–5126.)

### Field *semantics* are not yet pinned — and why

The register addressing, the field→byte provenance, and the full CAN→dongle path
above are **proven**. What each field physically *means* (which word is pack
voltage vs current vs SOC vs a cell min/max vs a version) is **not** determined
here, for a concrete reason: the parser is a straight little-endian byte copy with
**no scaling or naming**, so the meaning lives entirely in the battery's frame
definitions. Pinning them needs one of:

- the **battery image** (`BATT_IN280-Z03T13.bin`, HC32F460) decoded on the TX
  side — the ~3,900-instruction builder `FUN_0002a0bc` assembles these frames; it
  is proprietary/gitignored and was **not attached to the session** that mapped
  the ARM side, or
- a **live CAN capture** from a multi-pack stack (match known quantities by value).

An open question also remains on the **CAN id**: the ARM ingests per-pack on
**`0x4xx`** (`0x400|sub<<5|pack`), whereas §1's read of the battery TX table listed
per-pack frames at **`0x311–0x321`/`0x370–0x381`** (`0x3xx`) — and the battery's
own RX dispatcher treats `0x400` as an inbound *command* (§3). Whether this EG4-LL
pack actually emits the `0x4xx` telemetry the ARM parses (vs. a different/newer
pack or brand preset), or the `0x3xx` frames are remapped, is unresolved without
the battery image or a bus trace. So the 5000+ path is **present and provably
served**; that it is *fed* on this exact pack is the remaining unknown.

The most defensible semantic read (from the CAN-battery family + the aggregate
frames we do know, docs/20) is that the seven subtype frames carry the per-pack
analogs of the pack's V/I/SOC/SOH/temperature, min/max cell voltage & temperature,
charge/discharge limits, cycle count / capacity, and version/identity — but the
exact word-by-word assignment is deliberately left unlabeled rather than guessed.

**So the answer flips:** per-pack telemetry **is** readable over the dongle Modbus
on this `ceaa-07xx` image — just on a high, undocumented register bank (5000+)
that no public EG4 map lists, not in the IR 0–239 space. The ARM does **not**
aggregate to one logical pack after all; it keeps the per-pack detail and serves
it on the 5000 range.

> For **our** open firmware this *is* now a factory behaviour with an oracle
> (`test_per_pack_telemetry_reaches_modbus`), so per-pack visibility can be matched
> rather than treated as a superset — a `safety_cpu`-style module that fills a
> per-pack array and serves it on the 5000 range would do it (TDD target, not yet
> implemented).

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
