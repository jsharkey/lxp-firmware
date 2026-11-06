# IR 69-70 — RunningTime (L/H)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 69 | RunningTime L | 1 s | 32-bit low word |
| IR 70 | RunningTime H | 1 s | 32-bit high word |

## Where the data comes from

**ARM-local** — a cumulative run-time counter the ARM maintains. Clearable via
`HR 11` ResetSetting.EnergyRecordClr ("power and running time reset",
[`HR011-ResetSetting`](HR011-ResetSetting.md)). 32-bit value uses the
dongle's word+byte-swapped encoding.
