# HR 11 — ResetSetting (command bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

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
CAN1 ([`docs/wiring/ARM-CAN1`](../../wiring/ARM-CAN1-BMS.md)). Settings changes (bit 1)
are persisted to config flash.

**Factory handler (grounded).** docs/23 §Reset-to-default shows the write is
*flag-driven*: it sets request flags consumed by the super-loop (`sub_0801b3dc`)
subsystems. **Bit 7 (InvReboot)** is serviced by `sub_08035fe2`, a Cortex-M
`SYSRESETREQ` (`SCB->AIRCR 0xE000ED0C ← 0x05FA0004`) — both constants confirmed
present in the 07 image (T12). **Bit 1 (AlltoDefault)** reinitialises the settings
structs and marks the slots dirty so the writer re-flushes them. The remaining bits
match the table above (intent from the Modbus spec); a bit-exact per-bit handler
trace for bits 0/2/3/4/5/6 is not done.

**Our firmware (T12).** HR 11 is handled as a one-shot command (`src/state/command.c`
+ `inv_command_apply`): the register is **not stored** and reads back 0 after the
action. Wired: bit 0 → clear energy/runtime counters (`energy_reset_all`), bit 5/6 →
BMS charge/discharge switch requests, bit 7 → `SCB->AIRCR` reboot. Bits 1/2/3/4
(defaults / adj-ratio / fault & monitor records) are accepted and ignored for now
(docs/23 open items) rather than faked. See [`docs/31`](../../31-factory-quirks.md)
"OSS behaviour decisions".

> **Crash/freeze surface (confirmed).** This is the dongle's main remote-disruption
> lever, so it was checked for wedge/crash behaviour: a `0x06` write of **any** HR 11
> bit pattern — including bit 7 `InvReboot` and bit 1 `AlltoDefault` — echoes and
> leaves the ARM responsive in the RTOS emulation (no fault, no hang; the reboot did
> not manifest as a crash in-emu). It is a *command* register, not a stored value, so
> our reimplementation gates it behind an explicit writable-register allow-list rather
> than a plain write. Full audit: [`docs/44`](../../44-dongle-modbus-crash-surface.md),
> [`docs/31` Q14](../../31-factory-quirks.md).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Command dispatch (per bit):** [`test_command.c`](../../../tests/test_command.c) (`make test`) — each bit invokes exactly its op, NULL (unsupported) ops are skipped, reserved bits ignored, reboot runs last.
- **One-shot over the wire:** [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_hr11_resetsetting_is_one_shot_command` — a dongle write is acknowledged and the register reads back 0 (not stored).
