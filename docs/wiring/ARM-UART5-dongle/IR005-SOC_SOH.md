# IR 5 — SOC / SOH

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 5 | SOC (low byte) | % | 0-100 | state of charge |
| IR 5 | SOH (high byte) | % | 0-100 | state of health |

Per [`modbus_map.h`](../../../include/inv/modbus_map.h) `IR_SOC_SOH`, both pack into
**one** register (low=SOC, high=SOH). *(The spec prints them on adjacent rows; our
getter packs them into IR 5.)*

## Where the data comes from

**The battery BMS, over CAN1.** The pack publishes SOC/SOH in CAN frame `0x355`,
which the ARM's CAN parser `sub_0802a760` decodes and maps to IR 5
([`docs/20`](../../20-battery-bms-firmware.md) CAN→IR map,
[`docs/wiring/ARM-CAN1`](../../wiring/ARM-CAN1-BMS.md)). This is first-hand data — the
ARM reads the battery directly, not via the DSP or safety CPU.

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `SOC` = battery remaining power, `SOH` = battery health.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 5 (SOC/SOH):** battery CAN — [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_can_battery_telemetry_reaches_modbus` (0x355 → `(SOH<<8)|SOC`); decoder [`test_bms_can.c`](../../../tests/test_bms_can.c) (0x355).
