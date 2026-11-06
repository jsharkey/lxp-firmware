# IR 4 — Vbat (battery voltage)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 4 | Vbat | 0.1 V | 0-65535 |

## Where the data comes from

**Not yet pinned to a specific source.** Two candidates, both internal to the
ARM: the inverter-side battery sample on the USART2 bank (cf.
[`IR107-BatVoltSample_INV`](IR107-BatVoltSample_INV.md), `BANK+0x0a`), and
the BMS pack voltage over CAN1 ([`docs/20`](../../20-battery-bms-firmware.md)). The
register-getter sweep in [`docs/33`](../../33-usart2-telemetry-bank.md) did **not**
map IR 4 to a bank offset, so it is likely assembled/selected in ARM logic.
**Open:** trace the IR 4 getter.

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `Vbat` = battery voltage. Distinct from `Vbat_Inv` (inverter-sampled, IR 107).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 4 (Vbat):** battery CAN — [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_can_battery_telemetry_reaches_modbus` (0x356 voltage, 0.01 V → 0.1 V); decoder unit test [`test_bms_can.c`](../../../tests/test_bms_can.c) (0x356 voltage).
