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

- **IR 16 / IR 17 (Pinv/Prec):** ARM-computed, scaled on serve (T07) — [`test_telemetry.py`](../../../tests/test_telemetry.py) / [`telemetry_contract.py`](../../../tests/telemetry_contract.py) confirm `IR = (uint16_t)(internal_0.1W / 10)`. Host [`test_telemetry.c`](../../../tests/test_telemetry.c).
