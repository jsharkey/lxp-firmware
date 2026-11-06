# IR 77 — ACInputType

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | range | note |
|---|---|---|---|
| IR 77 | ACInputType | 0 or 1 | 0 = Grid, 1 = Generator (12K hybrid) |

## Where the data comes from

Reports whether the AC input is treated as grid or generator. **Open:** getter
source not yet pinned (candidate: derived from the generator-related settings /
line mode, [`HR146-LineMode`](HR146-LineMode.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
