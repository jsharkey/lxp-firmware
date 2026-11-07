# IR 19 — PF (power factor)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 19 | PF | 0.001 | 0-2000 | `BANK+0xaa` |

**Encoding (spec):** `PF ∈ (0,1000] → x/1000`; `PF ∈ (1000,2000) → (1000-x)/1000`
(the upper half encodes the leading/capacitive sign).

## Where the data comes from

**The USART2 bank** (`BANK+0xaa`), relayed over USART2
([`docs/33`](../../33-usart2-telemetry-bank.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Bank → IR serve (T07b):** [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY["pf"]` = bank `+0xaa` → IR 19, served **verbatim** (the raw 0-2000 encoded value; the client decodes the range). Our firmware's serve (`src/safety/safety_cpu.c`) is checked by [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_safety_cpu_telemetry_reaches_modbus`; the factory getter validates the same offset in [`test_arm_sim_factory_only.py`](../../../tests/test_arm_sim_factory_only.py) when run on a ceaa-07xx image.
