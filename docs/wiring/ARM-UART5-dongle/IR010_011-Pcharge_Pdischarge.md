# IR 10-11 — Pcharge / Pdischarge

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 10 | Pcharge | 1 W | 0-65535 | incoming battery power |
| IR 11 | Pdischarge | 1 W | 0-65535 | outflow battery power |

## Where the data comes from

**ARM-computed battery power** (sign split into charge vs discharge). Derived from
battery voltage × current inside the ARM's telemetry computation, alongside the
other `P*` powers ([`docs/22`](../../22-arm-dsp-core-split.md)); not a verbatim bank
field. **Open:** pin the exact current source (BMS CAN vs bank sample).

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `Pchg` = battery charge power, `Pdischg` = battery discharge power.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 10 / IR 11 (Pcharge/Pdischarge):** ARM-computed sign-split of the battery power, scaled on serve (T07) — [`test_telemetry.py`](../../../tests/test_telemetry.py) / [`telemetry_contract.py`](../../../tests/telemetry_contract.py) confirm `IR = (uint16_t)(internal_0.1W / 10)`. The getter applies no sign clamp of its own, so the charge/discharge split (each ≥ 0) is done upstream in the compute. Host [`test_telemetry.c`](../../../tests/test_telemetry.c).
