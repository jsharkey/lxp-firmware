# IR 15 — Fac (grid frequency)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 15 | Fac | 0.01 Hz | 0-65535 | `BANK+0x5e` |

## Where the data comes from

**The USART2 bank** (`BANK+0x5e`) — the safety CPU's own grid-frequency
measurement, relayed over USART2 ([`docs/33`](../../33-usart2-telemetry-bank.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Fgrid` = grid frequency.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 15 (Fac):** safety-CPU telemetry — [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`freq`, 0.01 Hz), asserted by `test_safety_cpu_telemetry_reaches_modbus`. Engine read path in [`test_modbus.c`](../../../tests/test_modbus.c).
