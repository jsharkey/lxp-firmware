# HR 112 — SetSystemType

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | values |
|---|---|---|
| HR 112 | SetSystemType | 0 non-parallel, 1 1-phase parallel (master), 2 slave, 3 3-phase parallel (master) |

## Side-effects of writing

**Parallel-system role.** Persisted to config flash; coordinates the
parallel-operation behaviour (reported back on the input side at
[`IR113-ParallelInfo`](IR113-ParallelInfo.md)). Parallel coordination
between inverters uses a CAN bus; a mismatch raises E008/E009/E010
([`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).
**Note space split:** HR 112/113 (settings) vs IR 113 (status).
