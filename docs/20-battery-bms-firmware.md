# The battery BMS image (`BATT`) — a fifth processor, and the far end of CAN1

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

Immediately after the table sits the manufacturer-name payload `EG4/LUX`
(the `0x35E`/`0x370` frame data). The `0x351/0x355/0x356/0x359` core is exactly
what a Victron/SMA/Deye/EG4 inverter expects to auto-configure charge limits and
display SOC — so our com-MCU firmware's battery-telemetry reader must parse this
set. The **Pylontech `0x42xx`** frame IDs (`0x4210/0x4220/0x4240/0x4290`, …) are
also present but **scattered**, built individually in code rather than from a
table (the Pylontech-style presets).

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

A black-box test of this contract is started in the GPIO/IO harness
([`docs/19`](19-gpio-test-harness.md)): `tests/arm_sim_can.py` (`CanBattery`)
stands in for the pack on CAN1, injecting telemetry frames (e.g. `0x355`
SOC/SOH) by modelling the bxCAN receive FIFO 0 at `0x40006400` — the registers
the com-MCU's **polled** reader touches (no IRQ; see the Status bind item above).
The common test `test_can_battery_soc_soh_reaches_modbus` injects a `0x355`
frame and checks the values surface on Modbus input register 5 (`IR_SOC_SOH`),
pinning the full **CAN → register image → Modbus** path.

Our com-MCU reimplementation now implements the receive side: `can_port_init` /
`can_port_poll` (`src/can/can_port.c`) bring up CAN1 (remapped to PB8/PB9) and
drain FIFO 0 each main-loop pass, `bms_can_on_frame` (`src/can/bms_can.c`,
host-tested by `tests/test_bms_can.c`) decodes `0x355`, and `main` publishes
SOC/SOH to `IR_SOC_SOH` — so the test **passes against our firmware**. The ARM
also sends a ~1 Hz keep-alive (`0x305`) to prompt the pack's telemetry.

It still **fails against the factory image**. The Modbus read-back half now
works (the dongle harness drives USART3 by interrupt), so the failure is on the
CAN ingest side: the factory's CAN RX is interrupt-driven (`IER` FMPIE0) and,
once the harness models the `MSR` init handshake and pends `CAN1_RX0`, its ISR
*does* drain the frame — but the decoded SOC/SOH still doesn't surface at
`IR_SOC_SOH`, because a further factory-internal step (CAN ring → consumer task
→ register image) isn't driven in the harness. Full breakdown in
[`docs/19` → *Why the factory is red*](19-gpio-test-harness.md).

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
