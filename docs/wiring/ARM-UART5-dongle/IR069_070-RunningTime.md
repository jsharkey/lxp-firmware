# IR 69-70 — RunningTime (L/H)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 69 | RunningTime L | 1 s | 32-bit low word |
| IR 70 | RunningTime H | 1 s | 32-bit high word |

## Where the data comes from

**ARM-local** — a cumulative run-time counter the ARM maintains. Clearable via
`HR 11` ResetSetting.EnergyRecordClr ("power and running time reset",
[`HR011-ResetSetting`](HR011-ResetSetting.md)). 32-bit value uses the
dongle's word+byte-swapped encoding.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 69 / IR 70 (RunningTime):** ARM-maintained u32 seconds counter served as a low/high register pair (T07) — [`test_telemetry.py`](../../../tests/test_telemetry.py) / [`telemetry_contract.py`](../../../tests/telemetry_contract.py) confirm IR 69 = `runtime & 0xFFFF`, IR 70 = `runtime >> 16`. The counter advances 1/s only while running (`op_state >= 3`, like the factory); host [`test_telemetry.c`](../../../tests/test_telemetry.c). (Cross-boot persistence is not yet reimplemented — follow-up.)
