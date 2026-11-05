# "Modbus" means several different things here — links, spaces, and a trap

A recurring source of confusion in this project is that the word *Modbus* covers
**several distinct things** in this system, and that register *numbers* are
**overloaded across register spaces**. This note disambiguates them and records
the AC-First-window observable that the disambiguation turned up.

## 1. One frame family, several uses

Everything on these serial links wears the same **EG4/Luxpower Modbus-family
envelope** — `addr`, function/type byte, a 10-byte `SN`, CRC-16/Modbus
([`docs/04`](04-modbus.md)). That shared envelope hides at least **three
different protocols**:

| # | use | role of the ARM | function/type codes | link | reference |
|---|---|---|---|---|---|
| 1 | **External monitoring dongle** (the RS-485 "dongle"/app) | Modbus **slave** | `0x03/0x04/0x06/0x10` | USART3 | [`docs/04`](04-modbus.md) |
| 2 | **ARM↔DSP config + telemetry** | Modbus **slave; the DSP polls as master** | register-group reads + an unsolicited clock push | USART3 ↔ DSP SCI-B | [`docs/05`](05-dsp-link.md), [`docs/08`](08-arm-dsp-config-protocol.md), [`docs/10`](10-dsp-config-field-map.md) |
| 3 | **Firmware update** | command target | extended `0x21/0x22/0x23` | USART3 | [`docs/05`](05-dsp-link.md) |

Consequences worth keeping in mind:

- **"A Modbus frame appeared on USART3" is ambiguous.** The dongle traffic and
  the DSP config traffic share the transport (a known placeholder collision in
  our port, see `src/dsp/dsp_link_port.c`). Match on address/function/CRC and the
  *shape* of the reply to tell which protocol a frame belongs to.
- **The ARM is a bridge, not just a slave.** It answers the external dongle
  *and* is polled by the DSP. [`docs/08`](08-arm-dsp-config-protocol.md) found a
  single serializer that runs in **two modes** — little-endian + `SN` for the
  dongle, big-endian + block-tagged for the DSP — selected by a runtime flag.
  *(That dual-mode detail is proven on the sibling `reference/com_flat.bin`
  image; in the ceaa-07xx factory image only the external-dongle path has been
  re-exercised black-box, via `tests/arm_sim_modbus.py`.)*
- **The DSP has no clock** ([`docs/09`](09-dsp-persistence-and-clock.md)). Any
  time-of-day decision is the ARM's; the DSP gets the raw window *values* (as
  register data) plus the ARM-streamed wall clock, and does its own thing with
  the real-time control — it is **not** handed the ARM's derived verdicts.

## 2. The register-number trap: spaces are separate number lines

The Modbus function code selects the **register space**, and the spaces are
**independent** — the same number means unrelated things in each:

| function codes | space | direction | holds |
|---|---|---|---|
| `0x03` / `0x06` / `0x10` | **holding** registers | read-write | settings / config |
| `0x04` | **input** registers | read-only | live telemetry / status |

So `126` is not one register:

- **Holding 126-131** = the **OptimalChg_DisChg** 48-slot 2-bit time table — a
  *configuration* block you write ([`include/inv/modbus_map.h`](../include/inv/modbus_map.h)).
- **Input 126** = a live **status word** read back from the device. In the
  ceaa-07xx factory image, **bit 8 of input register 126 is "AC-First window
  active now"** (§3).

Same number, different space, unrelated meaning. Mixing them up is what made an
earlier pass of this analysis conflate the AC-First window status with the
OptimalChg config. **When citing a register, always say which space** (we write
`HR nnn` for holding, `IR nnn` for input).

> **Map discrepancy to flag.** `modbus_map.h` labels `IR 126` as
> `IR_EGEN_ALL_H` (all-time generated energy, high word). The ceaa-07xx image
> clearly uses IR 126 as a **status word** instead (its value is a small
> bitfield, e.g. `0x0010`/`0x0110`, not an accumulating energy count). This is
> either model-specific or a gap in our map; do **not** assume `IR 126 = energy`
> for this image without checking. Follow-up: confirm the EG4 input-register
> definition for the 12000XP around 126.

## 3. Worked case — the AC-First window observable (ceaa-07xx, proven)

Tracing "where does the ARM compare the RTC against the AC-First windows, and
where does the result go?" end-to-end in the factory `.hex`:

**Comparison.** `sub_080352d0` reads the ARM calendar at `0x2000d850`
(`+1` = minute, `+2` = hour) → `now = 60·hour + minute`, and walks the **three
AC-First windows** at the slot-0 config buffer `0x2000c85c + 0x64`
(= **HR 152-157**; an HR 152/153 write lands byte-exactly there). Each window is
`u16 = (minute<<8)|hour`; a window is active iff **`start ≤ now < end`**
(start-inclusive, end-exclusive, with a midnight-wrap branch).

**Result storage — a single-reader funnel** (whole-image scan for every reader):

| location | written by | sole reader |
|---|---|---|
| `0x2000dbc2` per-window flag byte (bit *i* = window *i* active) | `sub_080352d0` | `sub_080352d0` (aggregation) |
| **bit 24 of `0x2000d890`** — "any AC-First window active" | `sub_080352d0` tail | **only** `sub_08035474` |
| **bit 4 of `0x2000da3a`** — telemetry mirror | `sub_08035474` | **only** `sub_08018d44` |

`sub_08018d44` is a telemetry **value computation** that writes a RAM status bank
(`0x2000d9b0…`, with float scaling constants) — **not** a UART/DSP frame builder.
That bank is what the external dongle reads. So the chain is:

```
sub_080352d0  →  0x2000dbc2  →  0x2000d890 bit24  →  0x2000da3a bit4  →  telemetry  →  IR 126 bit8
   (RTC vs HR152-157)        (aggregate)          (mirror, sub_08035474)  (sub_08018d44)   (external dongle)
```

**Not pushed to the DSP.** bit 24 and its mirror each have exactly one reader
(above); neither is a DSP-frame builder, and the DSP-bound frames are built from
register data + the streamed clock, not from the ARM's derived window verdict.
This matches [`docs/08`](08-arm-dsp-config-protocol.md)/[`docs/14`](14-arm-gpio-relay-acfirst.md)
on the sibling image ("the window decision ends in telemetry"), now re-proven in
ceaa-07xx from the comparison site forward.

**Black-box confirmation.** Driving the factory as a Modbus master
(`tests/arm_sim_modbus.py`): set window 0 = 06:00-08:00 (`HR 152/153`), set the
clock over the wire (`HR 13/14`), sweep it, and read `IR 126`:

| clock | IR 126 | bit 8 | verdict |
|---|---|---|---|
| 05:59 | `0x0010` | 0 | off |
| **06:00** | `0x0110` | 1 | **active** (start inclusive) |
| 07:30 | `0x0110` | 1 | active |
| **08:00** | `0x0010` | 0 | **off** (end exclusive) |

A full scan of input registers 0-255 finds **IR 126 bit 8 is the only one that
moves** with the window, and re-pointing the window (02:00-04:00 → 06:00-08:00)
moves the active band with it — so the bit tracks the configured times, not a
fixed range. The internal `0x2000d890` bit 24 moves in lock-step, corroborating
the chain.

**Test:** `tests/test_arm_sim.py::test_modbus_acfirst_window_tracks_rtc` pins
this as a black-box contract (currently TDD scaffolding for our own firmware,
which does not evaluate the AC-First windows against the RTC yet).

## Provenance

- **Proven in the ceaa-07xx factory image this round:** the external-dongle
  Modbus path (FC 3/4/6); the input-vs-holding register-space split; the AC-First
  comparison site `sub_080352d0` and its result funnel to `IR 126 bit 8`; and
  that the result is not pushed to the DSP (single-reader funnel + black-box IR
  scan).
- **Inherited from the sibling-image analysis** (cited inline): the dual-mode
  ARM↔DSP serializer, the firmware-update command path, and the DSP-side config
  block structure — see [`docs/05`](05-dsp-link.md), [`docs/08`](08-arm-dsp-config-protocol.md),
  [`docs/10`](10-dsp-config-field-map.md).
