# IR 107 — BatVoltSample_INV

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | bank offset |
|---|---|---|---|
| IR 107 | BatVoltSample_INV | 0.1 V | `BANK+0x0a` |

## Where the data comes from

**The USART2 bank** (`BANK+0x0a`) — the inverter-side battery-voltage sample,
relayed over USART2 ([`docs/33`](../../33-usart2-telemetry-bank.md)). This is the
inverter's *own* measurement of pack voltage, distinct from the BMS-reported pack
voltage and from IR 4 Vbat ([`IR004-Vbat`](IR004-Vbat.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `Vbat_Inv` = inverter sampling battery voltage (the inverter's own measurement, vs the BMS-reported pack voltage).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Bank → IR serve (T07b):** [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY["batv_inv"]` = bank `+0x0a` → IR 107, served verbatim (0.1 V). Our firmware's serve (`src/safety/safety_cpu.c`) is checked by [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_safety_cpu_telemetry_reaches_modbus`; the factory getter validates the same offset in [`test_arm_sim_factory_only.py`](../../../tests/test_arm_sim_factory_only.py) when run on a ceaa-07xx image. The tag-1 wire path (frame `+0x15` → bank `+0x0a`) is documented in [`docs/33`](../../33-usart2-telemetry-bank.md).
