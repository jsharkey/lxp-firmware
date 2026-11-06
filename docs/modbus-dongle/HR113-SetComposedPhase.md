# HR 113 — SetComposedPhase

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | values |
|---|---|---|
| HR 113 | SetComposedPhase | 1 R, 2 S, 3 T (phase assignment in a parallel system) |

## Side-effects of writing

**Assigns this unit's phase** in a 3-phase parallel system. Persisted to config
flash. **Do not confuse with IR 113** (ParallelInfo status) — different register
space, unrelated meaning (the "space split", [index](README.md)).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `Set Composed Phase` = **Phase U** | Phase V | Phase W (three-phase parallel).
