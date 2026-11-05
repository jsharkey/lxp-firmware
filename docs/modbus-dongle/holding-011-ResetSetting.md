# HR 11 — ResetSetting (command bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| bit | field | effect |
|---|---|---|
| 0 | EnergyRecordClr | power + running-time reset |
| 1 | AlltoDefault | restore system settings to defaults |
| 2 | AdjRatioClr | correction coefficient → default (1) |
| 3 | FaultRecordClr | clear fault record |
| 4 | MonitorData | clear offline monitoring records |
| 5 | BMSChgSWOn | turn on charge switch |
| 6 | BMSDischgSWOn | turn on discharge switch |
| 7 | InvReboot | restart inverter |
| 8-15 | rsvd | |

## Side-effects of writing

**Command register — each bit triggers an ARM-side action**, not a stored value.
Notably: bit 0 clears the energy/runtime counters
([`input-028_059-energy-counters`](input-028_059-energy-counters.md),
[`input-069_070-RunningTime`](input-069_070-RunningTime.md)); bit 7 reboots; bits
5/6 drive the **battery charge/discharge switches** which propagate to the BMS over
CAN1 ([`docs/wiring/ARM-CAN1`](../wiring/ARM-CAN1.md)). Settings changes (bit 1)
are persisted to config flash. **Open:** confirm the exact handler per bit.
