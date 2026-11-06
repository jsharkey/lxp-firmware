# IR 20-25 — EPS (off-grid) output

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | range | source |
|---|---|---|---|---|
| IR 20 | VepsR (L1) | 0.1 V | 0-65535 | USART2 bank `BANK+0x22` |
| IR 21 | VepsS (L2) | 0.1 V | 0-65535 | USART2 bank `BANK+0xd8/+0xdb` (two bytes) |
| IR 22 | VepsT | 0.1 V | 0-65535 | (3-phase; 18kPV) |
| IR 23 | Feps | 0.01 Hz | 0-65535 | EPS output frequency |
| IR 24 | Peps | 1 W | 0-65535 | EPS active power |
| IR 25 | Seps | 1 VA | 0-65535 | EPS apparent power |

## Where the data comes from

**Voltages (IR 20/21): the USART2 bank**, relayed over USART2 at the offsets above
([`docs/33`](../../33-usart2-telemetry-bank.md)). **Powers (IR 24/25) and frequency
(IR 23): ARM-computed/derived.** Split-phase L1N/L2N detail of the same EPS output
is at [`IR127_138-EPS-split-phase`](IR127_138-EPS-split-phase.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **UPS tab**: `Veps` = load voltage, `Feps` = load frequency, `VepsL1N`/`VepsL2N` = L1-N/L2-N load voltage, `Peps` = active power of load, `Seps` = apparent power of load.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 20 (VepsR) / IR 23 (Feps):** safety-CPU telemetry — [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`veps_r`, `feps`), asserted by `test_safety_cpu_telemetry_reaches_modbus`.
- **IR 24 (Peps) / IR 25 (Seps):** ARM-computed, served (T07) — [`test_telemetry.py`](../../../tests/test_telemetry.py) / [`telemetry_contract.py`](../../../tests/telemetry_contract.py): **Peps** is scaled `IR = (uint16_t)(internal_0.1W / 10)`; **Seps** (apparent power) is served **1:1 in VA** (no /10 — its getter reads a u16 source). Host [`test_telemetry.c`](../../../tests/test_telemetry.c).
- **IR 21 / 22 (VepsS / VepsT):** _No automated test exercises this register yet — a focused test is welcome._
