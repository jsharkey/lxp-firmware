# IR 16-17 — Pinv / Prec

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 16 | Pinv | 1 W | 0-65535 | inverter output power (grid port) |
| IR 17 | Prec | 1 W | 0-65535 | AC-charging rectified power |

## Where the data comes from

**ARM-computed** power values (part of the derived `P*` telemetry,
[`docs/22`](../../22-arm-dsp-core-split.md)), not verbatim bank fields.

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Pinv` = inverted power, `Prec` = rectified power.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
