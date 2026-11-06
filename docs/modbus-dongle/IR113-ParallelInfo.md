# IR 113 — ParallelInfo

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| field | bits | note |
|---|---|---|
| MasterOrSlave | 0-1 | 1 master, 2 slave |
| SingleOrThreePhase | 2-3 | 1 R, 2 S, 3 T |
| ParallelNum | 8-16 | number of parallel machines (1-255) |

*(Reserved bits 4-7.)*

## Where the data comes from

Parallel-system role/topology the ARM reports. Mirrors the parallel settings
written on the holding side ([`HR112-SetSystemType`](HR112-SetSystemType.md),
[`HR113-SetComposedPhase`](HR113-SetComposedPhase.md)). **Note the
space split:** IR 113 (this status) ≠ HR 113 (SetComposedPhase). **Open:** getter
source not individually traced.

## On the LCD (EG4 12000XP manual)

DATA MENU **Parallel tab**: `Parallel Role` (master/slave), `Parallel Type` (single/three phase), `Parallel Phase` (U/V/W), `Parallel Num`, `Parallel Addr`.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
