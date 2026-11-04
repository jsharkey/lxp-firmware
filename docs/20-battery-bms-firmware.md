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

### Open items (next passes)

- [ ] **Bus baud rate** — decode the HC32 CAN `SBT` bit-timing against the CAN
  clock. Expected **500 kbit/s** (universal for this frame family), to confirm.
- [ ] **Preset → frame-table binding** — find the selector that maps a `Pnn`
  preset to its active frame table / builders.
- [ ] **Per-frame byte layout** — map each `0x35x` TX frame's 8 bytes to the BMS
  data model (cell V, pack V/I, temps, SOC/SOH, limits, protect/alarm bitfields),
  and the inverter→battery `0x305/0x307` RX frames.
- [ ] **Exact HC32 SKU** + bootloader (`0x0`–`0x20000`) layout.
- [ ] Bind this contract to the com-MCU side (`include/inv/` + `docs/16` CAN1).

## Reproduce

```bash
python3 tools/batt_canmap.py BATT_IN280-Z03T13.bin        # base 0x20000 default
python3 tools/vt.py          BATT_IN280-Z03T13.bin --base 0x20000
```
