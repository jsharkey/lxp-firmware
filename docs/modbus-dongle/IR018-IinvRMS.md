# IR 18 — IinvRMS (inverter current RMS)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 18 | IinvRMS | 0.01 A | 0-65535 | `BANK+0x24` |

## Where the data comes from

**The USART2 bank** (`BANK+0x24`), relayed over USART2
([`docs/33`](../33-usart2-telemetry-bank.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **IR 18 (IinvRMS):** safety-CPU telemetry — [`arm_sim_contract.py`](../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`iinv`, **served ×10** — the scale is part of the contract), asserted by `test_safety_cpu_telemetry_reaches_modbus`.
