# Modbus register spaces, the UART links, and the one EG4-Modbus bus

Two recurring confusions, with the evidence-based answers for the ceaa-07xx
factory image. This note complements — and defers to — the UART/peer map in
[`docs/16`](16-arm-io-map.md) and the ARM/DSP split in
[`docs/22`](22-arm-dsp-core-split.md) / [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md);
read those for the DSP-link details. It also records the AC-First-window
observable that motivated the dig (§3).

> **Correction.** An earlier draft of this note (as `docs/22-modbus-multiplexing`)
> claimed the external dongle Modbus and the ARM↔DSP config "share USART3 (a
> placeholder collision)." **That was wrong** — it mistook our own firmware's
> placeholder (`src/dsp/dsp_link_port.c`) for the factory. The factory uses
> **separate UARTs**, as shown below. This file supersedes that draft.

## 1. The UARTs are five independent links — not one shared wire

Proven in ceaa-07xx (dynamic, under `tools/arm_sim.py`):

- **Five distinct, non-default interrupt handlers** — each UART is serviced
  independently (nothing shares the default handler):

  | IRQ | UART | ISR |
  |---|---|---|
  | 37 | USART1 | `sub_08005370` |
  | 38 | USART2 | `sub_0801bddc` |
  | 39 | USART3 | `sub_0801ba78` |
  | 52 | UART4  | `sub_0801c450` |
  | 53 | UART5  | `sub_0801c0b0` |

- **Post-boot baud divisors** (read out of `USART_BRR` after the firmware's own
  init; `APB1 = 60 MHz` on this GD32F303-class clone — the divisor that makes the
  EG4 baud come out exactly 19200, cross-checked by the other two ports landing
  on clean standard bauds):

  | UART | pins | BRR | baud | enabled | direction |
  |---|---|---|---|---|---|
  | USART1 | PA9/PA10 | `0x0000` | — | **no** (UE=0) | not brought up this boot |
  | USART2 | PA2/PA3 | `0x0c35` | **19200** | yes | **RX only** (RXNEIE) |
  | USART3 | PB10/PB11 | `0x0c35` | **19200** | yes | RX+TX (RXNEIE) |
  | UART4 | PC10/PC11 | `0x61a8` | **2400** | yes | RX+TX |
  | UART5 | PC12/PD2 | `0x186a` | **9600** | yes | RX+TX |

- **There is exactly one EG4-Modbus register slave, and it is USART3.** EG4
  Modbus runs at 19200 ([`docs/04`](04-modbus.md)); the only 19200 full-duplex
  port is USART3. A black-box probe (feed a framed `0x03` read, pend the RX IRQ,
  capture the TX) gets a **valid EG4 reply only on USART3** (`01 03 … CRC`,
  little-endian + 10-byte SN); the same request on USART2/UART4/UART5 draws no
  Modbus response. A transaction on USART3 touches **only** USART3's data
  register — it is a self-contained port, not a bus shared with another protocol.

### What this says about "dongle vs DSP on the same wire"

Your intuition holds: they are **not** one wire.

- **USART3** is the 19200 EG4-Modbus register interface, on an **RS-485** line
  (driver-enable on PA0, [`docs/16`](16-arm-io-map.md)) that also carries the
  firmware-update/bootloader path ([`docs/05`](05-dsp-link.md)). RS-485 is a
  **multidrop** bus by design, so an external EG4 monitoring dongle sharing it
  with other EG4 nodes — distinguished by Modbus address + the 10-byte SN — is
  the **standard, stable** EG4/Luxpower topology, not a risky hack.
- **USART2** (19200, **RX only**) is a separate TTL link carrying **DSP-domain
  telemetry** inbound (operating mode + PV/grid V/F → `0x20009e54`), decoded in
  [`docs/22`](22-arm-dsp-core-split.md). So the DSP's data path is its own wire,
  distinct from the RS-485 register bus.
- **UART4 (2400)** and **UART5 (9600)** are slower peers — a 2400 device (an
  external energy/CT meter is the usual 2400 citizen) and a 9600 device. Because
  EG4 Modbus is 19200, **UART5 at 9600 is unlikely to be the EG4 dongle**, which
  refines [`docs/16`](16-arm-io-map.md)'s "UART5 = dongle" guess — it is some
  other 9600 serial peer.

**Still open (defer to [`docs/16`](16-arm-io-map.md)/[`docs/22`](22-arm-dsp-core-split.md)/[`docs/23`](23-dsp-sci-a-crosscheck-handoff.md)):**
the precise DSP-vs-external attribution of the 19200 ports (is USART3 the
external RS-485 dongle, the DSP SCI-B that the DSP polls, or a multidrop bus the
DSP also sits on?), the ARM→DSP command/config TX port, and the UART4/UART5 peer
identities. These need the schematic or the DSP-side cross-check in progress. The
narrow, solid claim here: **the ARM exposes one 19200 EG4-Modbus register slave
(USART3), and DSP telemetry is a separate 19200 RX link (USART2).**

## 2. Register spaces: holding vs input (the "126" trap)

The Modbus function code selects the **register space**, and the spaces are
**independent number lines** — the same number means unrelated things in each:

| function codes | space | direction | holds |
|---|---|---|---|
| `0x03` / `0x06` / `0x10` | **holding** | read-write | settings / config |
| `0x04` | **input** | read-only | live telemetry / status |

So `126` is not one register:

- **Holding 126-131** = the **OptimalChg_DisChg** 48-slot 2-bit time table — a
  *configuration* block you write ([`include/inv/modbus_map.h`](../include/inv/modbus_map.h)).
- **Input 126** = a live **status word** you read back. In ceaa-07xx, **bit 8 of
  input register 126 is "AC-First window active now"** (§3).

Same number, different space, unrelated meaning — this is what made an earlier
pass conflate the AC-First status with the OptimalChg config. **Always say which
space** (`HR nnn` holding, `IR nnn` input).

> **Map discrepancy to flag.** `modbus_map.h` labels `IR 126` as `IR_EGEN_ALL_H`
> (all-time generated energy, high word). ceaa-07xx uses IR 126 as a **status
> word** (small bitfield, e.g. `0x0010`/`0x0110`, not an accumulating count).
> Either model-specific or a map gap — do **not** assume `IR 126 = energy` for
> this image. Follow-up: confirm the EG4 input-register definition near 126 for
> the 12000XP.

## 3. Worked case — the AC-First window observable (ceaa-07xx, proven)

"Where does the ARM compare the RTC to the AC-First windows, and where does the
result go?", end-to-end in the factory `.hex`:

**Comparison.** `sub_080352d0` reads the ARM calendar `0x2000d850` (`+1` minute,
`+2` hour) → `now = 60·hour + minute`, and walks the **three AC-First windows**
at slot-0 config buffer `0x2000c85c + 0x64` (= **HR 152-157**; an HR 152/153
write lands byte-exactly there). A window is active iff **`start ≤ now < end`**
(start-inclusive, end-exclusive; with a midnight-wrap branch).

**Result storage — a single-reader funnel** (whole-image scan for every reader):

| location | written by | sole reader |
|---|---|---|
| `0x2000dbc2` per-window flag (bit *i* = window *i*) | `sub_080352d0` | `sub_080352d0` |
| **bit 24 of `0x2000d890`** — "any AC-First window active" | `sub_080352d0` tail | **only** `sub_08035474` |
| **bit 4 of `0x2000da3a`** — telemetry mirror | `sub_08035474` | **only** `sub_08018d44` |

`sub_08018d44` is a telemetry **value computation** into a RAM status bank
(`0x2000d9b0…`, with float scaling) — not a UART/DSP frame builder. That bank is
read out over the EG4-Modbus register slave (USART3). The chain:

```
sub_080352d0 → 0x2000dbc2 → 0x2000d890 bit24 → 0x2000da3a bit4 → telemetry → IR 126 bit8
 (RTC vs HR152-157)      (aggregate)      (mirror, sub_08035474)  (sub_08018d44)  (Modbus slave)
```

**Not pushed to the DSP.** bit 24 and its mirror each have exactly one reader
(above); neither is a DSP-frame builder, and the DSP-bound traffic is register
data + the streamed clock, not the ARM's derived verdict. Matches
[`docs/08`](08-arm-dsp-config-protocol.md)/[`docs/14`](14-arm-gpio-relay-acfirst.md),
now re-proven in ceaa-07xx from the comparison site forward.

**Black-box confirmation.** Over the register slave (`tests/arm_sim_modbus.py`):
set window 0 = 06:00-08:00 (`HR 152/153`), set the clock over the wire
(`HR 13/14`), sweep it, read `IR 126`:

| clock | IR 126 | bit 8 | verdict |
|---|---|---|---|
| 05:59 | `0x0010` | 0 | off |
| **06:00** | `0x0110` | 1 | **active** (start inclusive) |
| 07:30 | `0x0110` | 1 | active |
| **08:00** | `0x0010` | 0 | **off** (end exclusive) |

A full IR 0-255 scan finds **IR 126 bit 8 is the only one that moves** with the
window, and re-pointing the window moves the active band with it — so the bit
tracks the configured times, not a fixed range. Internal `0x2000d890` bit 24
moves in lock-step.

**Test:** `tests/test_arm_sim.py::test_modbus_acfirst_window_tracks_rtc` pins
this black-box contract (TDD scaffolding for our firmware, which does not yet
evaluate the AC-First windows against the RTC).

## Provenance

- **Proven in ceaa-07xx this round:** five independent UART ISRs; the post-boot
  baud table (USART3/USART2 = 19200, UART4 = 2400, UART5 = 9600, USART1 off); a
  single EG4-Modbus register slave on USART3 (probe + DR-access trace); the
  input-vs-holding register-space split; and the AC-First comparison site
  `sub_080352d0` → `IR 126 bit 8` funnel, not pushed to the DSP.
- **Inherited / cross-referenced:** the DSP SCI-B identity and bootloader/CRC
  ([`docs/05`](05-dsp-link.md)); USART2 as DSP-domain telemetry and the ARM/DSP
  feedback-loop split ([`docs/22`](22-arm-dsp-core-split.md), [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md));
  the UART pin/peer map and RS-485 driver-enable pins ([`docs/16`](16-arm-io-map.md));
  and the dual-mode (LE+SN dongle vs BE block-tagged DSP) serializer
  ([`docs/08`](08-arm-dsp-config-protocol.md)).
