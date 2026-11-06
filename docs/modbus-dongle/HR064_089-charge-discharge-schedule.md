# HR 64-89 — charge/discharge schedule

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

Three parallel features, each = **PowerCMD % + SOCLimit % + three time windows**
(each window = start/end, packed `low=hour(0-23)`, `high=minute(0-59)`):

| feature | power | SOC | windows (start/end ×3) |
|---|---|---|---|
| AC-charge | 66 | 67 | 68-69, 70-71, 72-73 |
| Charge-priority | 74 | 75 | 76-77, 78-79, 80-81 |
| Forced-discharge | 82 | 83 | 84-85, 86-87, 88-89 |

(HR 64/65 are the general Charge/DischgPowerPercentCMD.)

## Side-effects of writing

**Persisted to config flash; the schedule is evaluated ARM-side against the
clock.** The time windows are checked against the RTC the ARM owns (the same
`hour|minute` packing as the AC-First windows), and the DSP pulls the relevant
holding-register groups over the link as part of the config snapshot
([`docs/08`](../08-arm-dsp-config-protocol.md)/[`docs/09`](../09-dsp-persistence-and-clock.md),
and the `modbus_map.h` block comment). The ARM decides *when* a window is active;
it does not push the per-window verdict as a separate signal
([`docs/25`](../25-modbus-register-spaces.md) establishes this pattern for the
AC-First window). Higher-resolution `0.1%` power variants live at HR 138-143.
