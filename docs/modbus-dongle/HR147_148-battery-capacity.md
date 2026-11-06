# HR 147-148 — battery capacity / nominal voltage

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| HR 147 | Battery capacity | Ah | 0-10000 | for unmatched batteries |
| HR 148 | Battery nominal Voltage | 0.1 V | 400-590 | for unmatched batteries |

## Side-effects of writing

**Manual battery parameters for "unmatched" (non-BMS) packs** — persisted to
config flash and used by the charge/discharge control (pushed to the DSP in the
config snapshot). For BMS packs these come from the pack over CAN1 instead
([`IR081_106-BMS`](IR081_106-BMS.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
