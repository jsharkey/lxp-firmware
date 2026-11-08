# IR 6 — InternalFault (internal DTC)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 6 | InternalFault | — | 0-65535 |

## Where the data comes from

**The USART2 safety bank**, `BANK+0xc8`, combined with an ARM-local DTC byte
(`STATUS+0x91`) before it is served ([`docs/33`](../../33-usart2-telemetry-bank.md)).
Verified on `ceaa-07xx` (T27): with the local DTC byte 0 (the normal/harness state),
IR 6 reads the bank word verbatim — writing `BANK+0xc8 = 0x1234` makes IR 6 = `0x1234`.
A diagnostic/trouble code distinct from the main fault bitfield (IR 60/61 — see
[`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Safety-CPU telemetry (T27):** IR 6 is a live bank mirror (`+0xc8`), in the shared
  `SAFETY_TELEMETRY` contract ([`arm_sim_contract.py`](../../../tests/arm_sim_contract.py))
  and asserted ours==factory by `test_safety_cpu_telemetry_reaches_modbus` and the
  per-image self/factory sweeps. Our firmware serves it from the bank
  ([`safety_cpu.c`](../../../src/safety/safety_cpu.c) `PUT(IR_INTERNAL_FAULT, +0xc8)`).
  The factory's extra OR of the ARM-local DTC byte (`STATUS+0x91`, 0 in the normal
  state) is a documented refinement (hand-off).
