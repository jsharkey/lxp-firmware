# The battery BMS image (`BATT`) — a fifth processor, and the far end of CAN1

> **Dongle registers:** for the dongle-facing view of the BMS registers (IR 81-106) see [`docs/wiring/ARM-UART5-dongle/IR081_106-BMS.md`](wiring/ARM-UART5-dongle/IR081_106-BMS.md). This doc remains the BMS image analysis + CAN frame contract.

> **Authoritative wiring:** the ARM-side CAN1↔BMS link is distilled in [`docs/wiring/ARM-CAN1-BMS.md`](wiring/ARM-CAN1-BMS.md). This doc remains the BMS image analysis and frame contract.

Analysis of the attached firmware `BATT_IN280-Z03T13.bin`
(72,904 bytes, crc32 `0x6571d6b2` / 1701959346, uncompressed, unencrypted).

**Verdict: this is the battery's BMS firmware — the peer that sits on the other
end of the inverter's "CAN1 / battery BMS bus"** (`docs/16-arm-io-map.md:53`,
PB8/PB9). It is *not* an inverter processor and shares no silicon with anything
in this repo: it runs on a **Huada / HDSC HC32-family** Cortex-M part, not an
STM32. But it is directly relevant to us, because the CAN frames it emits are
the contract our com-MCU firmware must speak to read the pack.

All *structural* facts below are direct reads of the image
(`tools/batt_canmap.py`, `tools/vt.py --base 0x20000`). The *roles* of
individual CAN IDs are matched against the well-known inverter "CAN bus battery"
protocol family (SMA/Victron/Pylontech-compatible) plus in-band strings; where a
label is an inference rather than an in-band string, it is marked.

> **Scope note.** This project reimplements the inverter's **ARM com MCU**. The
> battery BMS is a *separate product on a different MCU*; we do not plan to
> reimplement it. We characterize it only to pin down the CAN interface the
> inverter side depends on. The binary is a proprietary factory image and is
> **not committed** (`reference/*.bin` is gitignored); point the tools at a
> local copy.

## Not an STM32, and not loaded at 0

The vectors read `0x0002xxxx`, which is *past* the end of a 72 KB file if it were
based at 0. Solving for the base (which value lands the most code pointers inside
the file) gives **`0x00020000`**: 198/199 flash code-pointer words fall in range
at `0x20000` vs 188/199 at `0x18000`. So this is a flat **App** partition with a
**bootloader occupying `0x00000000`–`0x00020000`** below it (field-updatable —
consistent with the `hc32_ll_efm.c` flash driver being linked in).

| | inverter com MCU | **this `BATT` image** |
|---|---|---|
| Vendor / part | ST **STM32F103** high-density | **HDSC HC32F460-class** (Cortex-M4) |
| Flash map | `0x08000000` (ST alias) | `0x00000000` main flash, **App @ `0x20000`** |
| Driver library | ST StdPeriph (Keil) | **HDSC `hc32_ll_driver`** (Keil) |
| Initial SP | tens of KB into SRAM | `0x20001a40` (SRAM @ `0x20000000`) |
| Vector table | 60+ IRQ | **144-slot** HC32 IRQ table |
| Role | comms / HMI / supervisor | **battery management (BMS)** |

The chip identity is in-band and unambiguous — the Keil build left the HDSC LL
driver source paths in `.rodata`:

```
..\..\drivers\hc32_ll_driver\src\hc32_ll_can.c      (+ clk, usart, gpio,
..\..\drivers\hc32_ll_driver\src\hc32_ll_usart.c     pwc, efm, fcg, sram,
..\source\hc32_ll_efm.c                              interrupts)
```

Exact part number (flash/RAM size) is **TBC** — the `hc32_ll` tree and the
peripheral pages used (CAN `0x40021000`, a USART at `0x4001D000`, INTC/AOS
`0x40054000`, EFM `0x40010400`) are all HC32F460-consistent, but we have no
vendor header on hand to fix the exact SKU.

## It is unmistakably a BMS

The Keil image kept its RTOS/timer object names. They describe a stackable rack
LFP pack end-to-end:

| Symbol | Role |
|---|---|
| `BmsTimer` | main BMS service tick |
| `DSGMosSwitchTimer` | **discharge-MOSFET** switching (core protect path) |
| `CanTxTimer` / `ExtCanTimer` | CAN to inverter + external / inter-pack CAN |
| `LinkRs485Timer` + `…IdCheck` / `…Shutdown` / `…10Minute` | RS485 daisy-chain with **auto-addressing** (rack stacking) |
| `LcdReadDataLogTimer` / `LcdSlpTimer` | front LCD + data logging |
| `PanelRunLedTimer` | front-panel RUN LED |

Peripheral mix (by literal-pool reference count) agrees: heavy **CAN**
(`0x40021000`/`0x40021400`) and heavy **USART/RS485** (`0x4001D000`/`0x4001D400`),
plus GPIO, EFM, timers. Two comms fabrics — **CAN** (to the inverter) and
**RS485** (pack-to-pack / host) — is the standard server-rack battery topology.

## Identity strings

```
EG4-LL                 model line (EG4 "LL" rack battery)
LFP-12.8V  M25.6  M48.0  51.2VP   chemistry / module-nominal variants
Ah-V1.0                capacity/version tag
Z02T13   2026-02-10    app build tag + date  (package filename says Z03T13)
```

The app's in-band build tag is **`Z02T13`** dated **2026-02-10**, while the
delivered file is `…-Z03T13`; the package rev is one ahead of the app tag (likely
a bootloader/packaging bump). Model code `IN280` is from the filename only.

## The CAN link contract (why this matters to us)

### Selectable inverter-brand protocol presets

The BMS is **multi-protocol** — it carries a table of inverter-brand presets and
speaks whichever one is configured. Recovered preset strings:

| Preset | Target inverter |
|---|---|
| `P01-EG4` | EG4 (native) |
| `P02-GRW` | Growatt |
| `P03-SCH` / `P03-SLK` | Schneider / Sol-Ark (two list variants) |
| `P04-DY` | Deye |
| `P05-MGR` | (MegaRevo?) |
| `P06-VCT` | Victron |
| **`P07-LUX`** | **Luxpower** |
| `P08-SMA` | SMA |

**`P07-LUX` is the direct tie to this repo.** The inverter we reimplement is the
Luxpower-platform EG4 all-in-one; its CAN1 is labelled "battery BMS CAN bus" in
`docs/16`. So the inverter↔battery pairing is driven by this battery's `P07-LUX`
(or `P01-EG4`) profile, and the frames below are the bytes crossing that bus.

### The TX frame-ID table

A contiguous 32-bit descriptor table at **`0x00031a20`** holds the standard-11-bit
CAN IDs the pack transmits — the de-facto "CAN bus battery" protocol family:

```
core:     0x351 charge V/I limits   0x355 SOC/SOH      0x356 V/I/T
          0x359 protection/alarms    0x35a alarms       0x35b ext status
          0x35c charge-request flags 0x35e mfr name     0x35f fw/capacity
extended: 0x311–0x321, 0x370–0x381, 0x373/0x379  (per-cell, per-string, extras)
```

The **extended ranges carry the per-pack / stack-detail telemetry** (per-battery
summary, min/max cell voltage & temp, module counts, capacity, version, serial).
How the inverter treats them is decoded in
[the ingest map below](#what-the-inverter-does-with-the-extended-frames); the short
version is **only the aggregate block reaches the dongle** (IR 81–106). Full
dormant-`0x4xx`-bank and CAN firmware-update findings in
[`docs/34` — multi-battery CAN](34-multi-battery-can.md) (§2b).

Immediately after the table sits the manufacturer-name payload `EG4/LUX`
(the `0x35E`/`0x370` frame data). The `0x351/0x355/0x356/0x359` core is exactly
what a Victron/SMA/Deye/EG4 inverter expects to auto-configure charge limits and
display SOC — so our com-MCU firmware's battery-telemetry reader must parse this
set. The **Pylontech `0x42xx`** frame IDs (`0x4210/0x4220/0x4240/0x4290`, …) are
also present but **scattered**, built individually in code rather than from a
table (the Pylontech-style presets). *(These `0x42xx` Pylontech frames are a
different preset — `0x42xx & 0xf00 = 0x200`, not the ARM per-pack bank's `0x4xx`
gate — and are not emitted to our LUX inverter.)*

## What the inverter does with the extended frames

Decoded the ARM's CAN-ID dispatch (`sub_08021694`/`sub_08021a1c`/`sub_08021b68`)
to see which of the battery's `0x3xx` frames the inverter actually ingests, and
where each lands. Across all three EG4 packs (which emit the same families —
`IN280`/`AW280` identical, `WM314`/EG4-314 adds `0x322–0x329`), the picture is:

| battery frames | inverter handler | lands in | on the dongle? |
|---|---|---|---|
| **aggregate** `0x351/355/356/359/35a/35b/35c/35e/35f` | `sub_08021694` + `sub_08021a1c` | the input-register image | **✔ served** — [IR 81–106](wiring/ARM-UART5-dongle/IR081_106-BMS.md), IR 5 |
| **extended** `0x311–0x321` | `sub_08021b68` | fixed scalar RAM (`0x2000a87e…0x2000a8a2`, `0x2000a9b2…0x2000a9c2`) | ✗ — consumed only by internal CAN re-forwarders (`sub_0802138e`/`sub_08021850`), **not** read by the Modbus getters |
| **cell / stack detail** `0x370–0x381` (min/max cell V & T, module counts, capacity, SW/HW version, serial) | **none** | — | ✗ — **not parsed at all**; the ARM has no `0x370–0x381` dispatch (verified: zero CAN-id compares in that range). Received on the bus and dropped. |
| **per-pack bank** (CAN `0x400|sub<<5|pack`) | `sub_080205d4` → IR 5000–5126 | per-pack array `0x2000691c` | ✗ — real path, but **no EG4 pack emits `0x4xx`** (docs/34 §2b), so dormant |

So beyond the aggregate pack summary, **no per-battery or per-cell detail is
reachable from this inverter** — the richest frames (`0x370–0x381`: cell min/max
V/T, capacity, version, serial) are not even parsed, and `0x311–0x321` go to
internal scalars that never reach a register.

### `0x311–0x321` byte layout (what the ARM extracts)

Authoritative *structure* from `sub_08021b68` (big-endian; the scalars are
internal and unnamed — the inverter re-forwards them, it does not serve or, as far
as traced, display them, so a semantic label would be a guess and is left open):

| frame | bytes → scalar |
|---|---|
| `0x311` | `[0:1]→a8a2`, `[2:3]→a88c`, `[4:5]→a88e` (BE u16 ×3) |
| `0x312` | `[0]→a9b5`, `[1]→a9b6`, `[2]→a9b7`, `[3]→a9b8`, `[4]→a9b2` (u8 ×5 — status/flags) |
| `0x313` | `[0:1]→a87e`, `[2:3]→a880`, `[4:5]→a882`, `[6]→a884`, `[7]→a886` |
| `0x314` | `[6:7]→a8a0` |
| `0x319` | `[0]→a9b9`, `[1:2]→a898`, `[3:4]→a89a` |
| `0x321` | `[0:1]→a89c`, `[2:3]→a89e` |

(The `a87e…a8a2` cluster is BE u16 measurements; `a9b2…a9c2` are u8 status bytes —
consistent with per-string summary + flags, but their exact meaning needs the EG4
extended-CAN spec or a live capture, neither of which is in hand. The `0x370–0x381`
cell detail would be the clean min/max-cell set, but since the inverter never reads
it, its layout isn't recoverable from this image's parse.)

## Per-frame byte layout (recovered)

The TX side is one large builder, **`FUN_0002a0bc`** (~3,900 insns, handles all
presets via branches). It fills a RAM **CAN descriptor array** whose records are
**16 bytes** each:

```
record[n] @ 16*n:  { u32 can_id; u32 dlc; u8 data[8] }   // data at record+8
```

The builder's tail block stamps the IDs next to their data, giving the
record→ID map for the **standard (little-endian) preset**:

| record | +0 id | data bytes | frame |
|---|---|---|---|
| `0x00` | `0x351` | `0x08–0x0f` | charge/discharge limits |
| `0x10` | `0x355` | `0x18–0x1f` | SOC / SOH |
| `0x20` | `0x356` | `0x28–0x2f` | voltage / current / temp |
| `0x30` | `0x35a` | `0x38–0x3f` | alarms |
| `0x40` | `0x35b` | `0x48–0x4f` | extended status |
| `0x60` | `0x35f` | `0x68–0x6f` | firmware / capacity |

Byte-exact field layouts (direct reads of the builder — see
`include/inv/bms_can_map.h` for the C form):

**`0x351` — limits** (DLC 8, little-endian):

| bytes | field | scaling | source |
|---|---|---|---|
| 0–1 | charge voltage limit | ×0.1 V | model-selected: `0x230`=56.0 V (51.2 V pack), `0x118`=28.0 V (25.6 V), `0x8c`=14.0 V (12.8 V) |
| 2–3 | max charge current | ×0.1 A | `FUN_00029338`×10, clamp `0x7530`=3000.0 A |
| 4–5 | max discharge current | ×0.1 A | `FUN_0002935c`×10, clamp 3000.0 A |
| 6–7 | discharge voltage limit | ×0.1 V | model-selected: `0x1c2`=45.0 V (51.2 V pack) |

The charge-/discharge-voltage branches key off a pack-class config register
(`==4` / `==8` / `==0xf` / else) — exactly the **M25.6 / M48.0 / 51.2VP** module
variants named in the identity strings.

**`0x355` — SOC/SOH** (DLC 6, little-endian): `[0:1]` SOC % (`FUN_000291f6`),
`[2:3]` SOH % (`FUN_00029380`), `[4:5]` SOC high-res ×0.01 % (= SOC×100).

**`0x356` — measurements** (DLC 6, little-endian, signed): `[0:1]` pack voltage
×0.01 V (`FUN_000296f8`), `[2:3]` current ×0.1 A s16 (`FUN_00029478`), `[4:5]`
temperature ×0.1 °C s16 (`FUN_000296b4`×10).

These three match the industry-standard "CAN bus battery" layout exactly.

> **Endianness is preset-dependent.** The tail block above is little-endian
> (standard). A *different* preset path at the top of the same builder
> (`0x2a128…`) packs the same fields **big-endian** (MSB at the low byte). Byte
> order therefore depends on the active `Pnn` preset — do not assume one.

### Inverter → battery (RX), `FUN_0002314c`

The RX dispatcher walks a matching 16-byte-record receive table and decodes
inverter→battery IDs **`0x300`** (request), **`0x301`** (config/handshake, 8-byte
copy), **`0x305`** (keep-alive), and **`0x400`** (command — `data[0]==1` drives a
state action via `FUN_00030af0`). RX parsing is also gated by the active-preset
byte (`==1` / `==5` / `==6` branches).

### Status

- [x] **Per-frame byte layout** — descriptor structure + `0x351`/`0x355`/`0x356`
  byte-exact (standard preset); RX IDs `0x300/0x301/0x305/0x400` identified.
  Captured in `include/inv/bms_can_map.h`.
- [ ] **Alarm/flag bit maps** (`0x359`/`0x35a`/`0x35c`) — positions partially
  recovered; finish the exact standard-bit assignment.
- [ ] **Bus baud rate** — decode the HC32 CAN `SBT` bit-timing. Expected 500 kbit/s.
- [ ] **Per-preset byte-order/table map** — which `Pnn` preset selects which
  builder path (and endianness).
- [ ] **Exact HC32 SKU** + bootloader (`0x0`–`0x20000`) layout.
- [x] **Bind this contract to the com-MCU side** — done: Init
  `sub_08022660`/`sub_080227b6`, RX handler `sub_08005758` → ring `0x200051ac`,
  parser `sub_0802a760` (dispatches the `0x350–0x360` core +
  `0x300`/`0x370–0x38c`/`0x4xx` IDs), TX `sub_0800574c`. See
  [`docs/16` → "CAN1 ↔ battery BMS"](16-arm-io-map.md).
- [x] **RX is interrupt-driven, not polled** *(corrects an earlier note)* —
  harness instrumentation of the factory image shows it writes `CAN1->IER = 0x2`
  (**FMPIE0**, FIFO-0-message-pending interrupt) and **never reads `RF0R`**;
  pending the `CAN1_RX0` interrupt (vector 16+20) makes its ISR drain the FIFO-0
  mailbox. So `sub_08005758` is the RX **ISR**, reached via NVIC, not a poll
  loop. Its CAN init also busy-waits on the `CAN1->MSR` `INRQ→INAK` enter/leave-
  init handshake (and `SLEEP→SLAK`). See docs/19 → *Why the factory is red*.

## Testing the CAN contract (harness scaffolding)

A black-box test of this contract lives in the GPIO/IO harness
([`docs/19`](19-gpio-test-harness.md)): `tests/arm_sim_can.py` (`CanBattery`)
stands in for the pack on CAN1, injecting telemetry frames by modelling the
bxCAN receive FIFO 0 at `0x40006400`. The common test
`test_can_battery_telemetry_reaches_modbus` injects the core frames and checks
the values surface on the right Modbus input registers, pinning the full
**CAN → register image → Modbus** path.

**CAN → Modbus map (recovered from the factory oracle, cross-checked vs the EG4
Modbus doc).** The factory image is the reference for both register choice and
scaling; our firmware matches it, so the one test passes on both:

| CAN field | → IR | scaling |
|---|---|---|
| `0x355` [0:1] SOC % / [2:3] SOH % | 5 `SOC/SOH` | low byte / high byte |
| `0x356` [0:1] voltage | 4 `Vbat` | 0.01 V → 0.1 V, **rounded** |
| `0x356` [2:3] current (s16) | 98 `BatCurrent_BMS` | 0.01 A, 1:1 |
| `0x356` [4:5] temperature (s16) | 103 `MaxCellTemp_BMS` | 0.1 °C, 1:1 |
| `0x351` [0:1] charge-V limit | 83 `ChargeVoltRef` | 0.1 V, 1:1, then the factory **clamps** to a cell-count max (~57.4 V here) |
| `0x359` [0:1] protection bits | 99 `FaultCode_BMS` | bitfield, 1:1 |
| `0x359` [2:3] alarm bits | 100 `WarningCode_BMS` | bitfield, 1:1 |
| `0x359` [4] module count | 96 `BatParallelNum` | 1:1 |

The factory also mirrors the `0x359` protection/alarm words into IR 88/89
(`BatStatus3/4`, duplicates we don't bother reproducing), and has quirks in this
area — `0x355` [4:5] → IR 101 (a 7.7 V "cell"), the `0x359` `"PN"` marker → IR 97
capacity, and `0x35A` received but never published — catalogued in
[`docs/31` — factory quirks](31-factory-quirks.md).

**Not yet flowed (needs more RE):** `0x35C` (charge/discharge request flags) is
*bit-translated* into IR 87 (`BatStatus2`) and IR 95 (`BatStatus_INV`) — not a
raw copy (e.g. request bits 4/5 → `0x10`, bit 6 → `0x02`, bit 7 → `0x01` in
IR 95; IR 87 carries the raw request byte in its high byte with bit 3 dropped).
Flowing it faithfully needs the per-bit flag semantics decoded first. `0x35B`
(ext status) / `0x35E` / `0x35F` reach none of these registers.

Our com-MCU reimplementation implements the receive side: `can_port_init` /
`can_port_poll` (`src/can/can_port.c`) bring up CAN1 (remapped to PB8/PB9) and
drain FIFO 0 each main-loop pass, `bms_can_on_frame` (`src/can/bms_can.c`,
host-tested by `tests/test_bms_can.c`) decodes `0x355`/`0x356`/`0x351`, and
`main` publishes the fields above (with the scalings) into the register image.
The ARM also sends a ~1 Hz keep-alive (`0x305`) to prompt the pack's telemetry.

The test now **passes against both images**. The factory reaches the same result
by a different path: its CAN RX is interrupt-driven (it sets `CAN_IER` **FMPIE0**
and receives in the `CAN1_RX0` ISR, *not* a poll loop — correcting the bind item
above), and a periodic task copies the decoded SOC/SOH into its register image
(observed at RAM `0x2000d7b0`) a scheduler cycle later. The `CanBattery` harness
drives that by modelling the CAN `MSR` init handshake and pending `CAN1_RX0`, and
the test `settle()`s to let the consumer task publish before polling. Full
write-up in [`docs/19` → *How both images pass*](19-gpio-test-harness.md).

## Reproduce the frame analysis

```bash
python3 tools/recurse.py   BATT_IN280-Z03T13.bin --base 0x20000 --out /tmp/batt_ref
python3 tools/batt_canmap.py BATT_IN280-Z03T13.bin --builders   # locate ID builders/handlers
```

## Reproduce

```bash
python3 tools/batt_canmap.py BATT_IN280-Z03T13.bin        # base 0x20000 default
python3 tools/vt.py          BATT_IN280-Z03T13.bin --base 0x20000
```
