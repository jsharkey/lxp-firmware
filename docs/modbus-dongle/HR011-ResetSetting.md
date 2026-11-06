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
([`IR028_059-energy-counters`](IR028_059-energy-counters.md),
[`IR069_070-RunningTime`](IR069_070-RunningTime.md)); bit 7 reboots; bits
5/6 drive the **battery charge/discharge switches** which propagate to the BMS over
CAN1 ([`docs/wiring/ARM-CAN1`](../wiring/ARM-CAN1.md)). Settings changes (bit 1)
are persisted to config flash. **Open:** confirm the exact handler per bit.

> **Crash/freeze surface (confirmed).** This is the dongle's main
> remote-disruption lever, so it was checked for wedge/crash behaviour: a `0x06`
> write of **any** HR 11 bit pattern — including bit 7 `InvReboot` and bit 1
> `AlltoDefault` — echoes and leaves the ARM responsive in the RTOS emulation (no
> fault, no hang; the reboot did not manifest as a crash in-emu). It is a
> *command* register, not a stored value, so our reimplementation must gate it
> behind an explicit writable-register allow-list rather than treat it as a plain
> write. See the full audit in
> [`docs/38`](../38-dongle-modbus-crash-surface.md) and
> [`docs/31` Q8](../31-factory-quirks.md).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **Crash-surface audit (manual/dynamic, not yet a committed test):** all HR 11
  bit patterns injected via [`tests/arm_sim_modbus.py`](../../tests/arm_sim_modbus.py)
  against the factory image stay crash-free ([`docs/38`](../38-dongle-modbus-crash-surface.md)).
  A committed `arm_sim`-based regression that writes HR 11 and asserts the slave
  still answers would be welcome.
