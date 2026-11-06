# IR 5 — SOC / SOH

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 5 | SOC (low byte) | % | 0-100 | state of charge |
| IR 5 | SOH (high byte) | % | 0-100 | state of health |

Per [`modbus_map.h`](../../include/inv/modbus_map.h) `IR_SOC_SOH`, both pack into
**one** register (low=SOC, high=SOH). *(The spec prints them on adjacent rows; our
getter packs them into IR 5.)*

## Where the data comes from

**The battery BMS, over CAN1.** The pack publishes SOC/SOH in CAN frame `0x355`,
which the ARM's CAN parser `sub_0802a760` decodes and maps to IR 5
([`docs/20`](../20-battery-bms-firmware.md) CAN→IR map,
[`docs/wiring/ARM-CAN1`](../wiring/ARM-CAN1.md)). This is first-hand data — the
ARM reads the battery directly, not via the DSP or safety CPU.

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `SOC` = battery remaining power, `SOH` = battery health.
