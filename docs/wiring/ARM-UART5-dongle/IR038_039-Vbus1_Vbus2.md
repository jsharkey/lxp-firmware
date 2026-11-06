# IR 38-39 — Vbus1 / Vbus2

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 38 | Vbus1 | 0.1 V | 0-65535 | `BANK+0x0e` |
| IR 39 | Vbus2 | 0.1 V | 0-65535 | `BANK+0x10` |

## Where the data comes from

**The USART2 bank** at the offsets above, relayed over USART2
([`docs/33`](../../33-usart2-telemetry-bank.md)). Half-bus voltage is a separate
register — [`IR120-VBusP`](IR120-VBusP.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **Other tab**: `Vbus1` = voltage of BUS1, `Vbus2` = voltage of BUS2.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 38 / 39 (Vbus1/Vbus2):** safety-CPU telemetry — [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`vbus1`/`vbus2`), asserted by `test_safety_cpu_telemetry_reaches_modbus`. The engine group-boundary test in [`test_modbus.c`](../../../tests/test_modbus.c) also starts at 38.
