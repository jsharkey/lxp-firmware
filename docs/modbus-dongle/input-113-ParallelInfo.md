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
written on the holding side ([`holding-112-SetSystemType`](holding-112-SetSystemType.md),
[`holding-113-SetComposedPhase`](holding-113-SetComposedPhase.md)). **Note the
space split:** IR 113 (this status) ≠ HR 113 (SetComposedPhase). **Open:** getter
source not individually traced.
