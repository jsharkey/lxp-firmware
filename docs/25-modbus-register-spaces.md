# Modbus register spaces, the UART links, and the one EG4-Modbus bus

> **Authoritative wiring:** the per-UART link details live in [`docs/wiring/`](wiring/README.md). **Note:** §1's "USART2 carries DSP-domain telemetry" is superseded — USART2's peer is the safety CPU, and the bank's measured values are its own (see [`ARM-USART2.md`](wiring/ARM-USART2.md)).

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

> **Superseded — dongle attribution (see [`docs/26`](26-dongle-firmware.md)).**
> §1 below concluded the external dongle talks to a register slave on **USART3**
> and that **"UART5 at 9600 is unlikely to be the dongle."** That attribution is
> **retracted.** Three things overturn it:
> 1. The dongle's *own* firmware ([`docs/26`](26-dongle-firmware.md)) shows it is
>    an RS-485 **half-duplex master** with a **field-configurable baud** — so a
>    9600 UART5 is exactly a dongle set to the inverter's rate. The "EG4 Modbus is
>    19200 → not UART5" argument does not hold; baud is not a discriminator.
> 2. Static RE ([`docs/08`](08-arm-dsp-config-protocol.md)) locates the dongle's
>    standard-Modbus register handler `sub_0802afe2` on **UART5 `0x40005000`**
>    (RX buffer `0x20008ca4`) — the handler is on UART5, not USART3.
> 3. The black-box probe below saw "no reply on UART5" because that handler is a
>    **gated scheduler task** a cold probe can't start (docs/08 says so in as many
>    words) — a **false negative**, not evidence against UART5. What *did* answer
>    on USART3 is the ARM's dual-mode bridge serializer in its LE+SN ("dongle")
>    mode (`sub_0803373c`, flag `0x2000aa0b` bit 0 — docs/08) and/or simply the
>    port our own harness is wired to (our reimplementation binds Modbus to
>    USART3 — docs/04).
>
> **Corrected map: dongle = UART5; USART3 = the ARM↔DSP (SCI-B) bridge + bootloader
> link.** The baud table, the register-space split (§2) and the AC-First
> observable (§3) are all unaffected — note only that §3's harness reaches those
> registers over USART3 as a *reimplementation* convenience, while the factory
> serves the dongle on UART5.

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

- **A framed EG4 `0x03` read gets a reply on USART3 in our harness** (feed the
  read, pend the RX IRQ, capture the TX → `01 03 … CRC`, little-endian + 10-byte
  SN); the same request on USART2/UART4/UART5 draws nothing. **This does *not*
  mean USART3 is the dongle port** (see the Superseded banner above): the reply
  on USART3 is the ARM's dual-mode bridge serializer in LE+SN mode and/or the
  port our reimplementation wires Modbus to, and the UART5 silence is a false
  negative — its dongle handler `sub_0802afe2` is a gated scheduler task the cold
  probe can't start (docs/08). The useful, attribution-independent fact the probe
  does establish: each UART is a **self-contained port** whose transaction touches
  only its own data register — the links are not one shared wire.

### What this says about "dongle vs DSP on the same wire"

Your intuition holds: they are **not** one wire. The corrected per-link map
(see the banner; [`docs/16`](16-arm-io-map.md)/[`docs/08`](08-arm-dsp-config-protocol.md)/[`docs/26`](26-dongle-firmware.md)):

- **USART3** (19200, RX+TX) is the **ARM↔DSP (SCI-B)** link — the ARM pushes
  config (dual-mode serializer `sub_0803373c`, BE+block-tagged to the DSP) and
  the firmware-update/bootloader `0x21/0x22/0x23` ([`docs/05`](05-dsp-link.md),
  [`docs/08`](08-arm-dsp-config-protocol.md)). It is *not* the external dongle.
- **USART2** (19200, **RX only**) carries **DSP-domain telemetry** inbound
  (operating mode + PV/grid V/F → `0x20009e54`), decoded in
  [`docs/22`](22-arm-dsp-core-split.md).
- **UART5 (9600)** is the **external RS-485 dongle / EG4-Modbus register slave** —
  handler `sub_0802afe2` at `0x40005000`, buffer `0x20008ca4`
  ([`docs/08`](08-arm-dsp-config-protocol.md)), confirmed from the dongle side as
  an RS-485 half-duplex **master** with configurable baud
  ([`docs/26`](26-dongle-firmware.md)). The dongle is configured to UART5's 9600;
  the earlier "19200 ⇒ not UART5" reasoning is void (baud is configurable).
- **UART4 (2400)** is a slower external peer (a 2400 device — an external
  energy/CT meter is the usual 2400 citizen); still unidentified.

**Still open:** the ARM→DSP command/config TX pin pairing (schematic-level) and
the **UART4** peer identity. The dongle-vs-DSP attribution that §1 originally left
open is now **resolved**: **dongle = UART5, DSP = USART3** (static handler on
UART5 + the dongle-firmware corroboration above).

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
read out over the EG4-Modbus register slave (reached via our USART3-wired harness;
the factory serves this to the dongle on UART5 — see the banner). The chain:

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
  baud table (USART3/USART2 = 19200, UART4 = 2400, UART5 = 9600, USART1 off); an
  EG4-Modbus register slave responding over USART3 **in our harness** (probe +
  DR-access trace) — now understood as the ARM↔DSP bridge path / our own Modbus
  binding, **not** the dongle port, which is UART5 (banner, docs/08, docs/26); the
  input-vs-holding register-space split; and the AC-First comparison site
  `sub_080352d0` → `IR 126 bit 8` funnel, not pushed to the DSP.
- **Inherited / cross-referenced:** the DSP SCI-B identity and bootloader/CRC
  ([`docs/05`](05-dsp-link.md)); USART2 as DSP-domain telemetry and the ARM/DSP
  feedback-loop split ([`docs/22`](22-arm-dsp-core-split.md), [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md));
  the UART pin/peer map and RS-485 driver-enable pins ([`docs/16`](16-arm-io-map.md));
  and the dual-mode (LE+SN dongle vs BE block-tagged DSP) serializer
  ([`docs/08`](08-arm-dsp-config-protocol.md)).
