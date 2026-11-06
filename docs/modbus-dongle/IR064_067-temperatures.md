# IR 64-67 — temperatures

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | source |
|---|---|---|---|---|
| IR 64 | Tinner | 1 °C (s16) | 0-65535 | internal ring temp — *not yet traced* |
| IR 65 | Tradiator1 | 1 °C (s16) | 0-65535 | USART2 bank `BANK+0x1e` |
| IR 66 | Tradiator2 | 1 °C (s16) | 0-65535 | USART2 bank `BANK+0x1c` |
| IR 67 | Tbat | 1 °C (s16) | 0-65535 | battery temp — likely BMS/CAN1 |

## Where the data comes from

**Radiator temps (IR 65/66): the USART2 bank** at `BANK+0x1e`/`+0x1c`
([`docs/33`](../33-usart2-telemetry-bank.md)). **Tbat (IR 67)** is battery
temperature — most likely from the BMS over CAN1
([`docs/20`](../20-battery-bms-firmware.md)); **Tinner (IR 64)** is not yet mapped
to a getter source. All are signed (`s16`).

## On the LCD (EG4 12000XP manual)

The manual's DATA MENU **Other tab** also reports two inverter temperatures with thresholds: `T1` = I/O-board temp, highest (Normal <87 °C, Warning >87 °C, Fault ≥95 °C); `T2` = motherboard temp (Normal <90 °C, Warning >90 °C, Fault ≥105 °C). Their exact correspondence to Tinner/Tradiator1/2 here is not pinned. (Cell temps `Tcellmax`/`Tcellmin` are the BMS's, IR 103/104.)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **IR 65 / 66 (Tradiator1/2):** safety-CPU telemetry — [`arm_sim_contract.py`](../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`t_rad1`/`t_rad2`, **served /10**), asserted by `test_safety_cpu_telemetry_reaches_modbus`.
- **IR 64 (Tinner) / IR 67 (Tbat):** _No automated test exercises this register yet — a focused test is welcome._
