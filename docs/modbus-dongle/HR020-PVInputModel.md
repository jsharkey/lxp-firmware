# HR 20 — PVInputModel

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | range | note |
|---|---|---|---|
| HR 20 | PVInputModel | 0-4 (0-7 for 12K hybrid) | PV routing / parallel config |

0 no PV, 1 PV1, 2 PV2, 3 two parallel PV, 4 two separate PV (18kPV extends 0-7).

## Side-effects of writing

**A DSP-relevant configuration value** — persisted to config flash and pushed to
the DSP as part of the full config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)/[`docs/10`](../10-dsp-config-field-map.md),
[`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md)). Tells the power stage how the
PV inputs are wired. **Open:** its exact offset in the DSP config block.

## On the LCD (EG4 12000XP manual)

SETTINGS → **Common tab**: `PV Input Mode` = `DC source input` | `Two MPPT connect to different strings` — **factory default: Two MPPT to different strings**. ('Same string' parallels both strings into one MPPT at the inverter.)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
