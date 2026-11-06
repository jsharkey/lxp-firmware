# IR 12-14 — VacR / VacS / VacT (grid voltage)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 12 | VacR (L1) | 0.1 V | 0-65535 | `BANK+0x20` |
| IR 13 | VacS (L2) | 0.1 V | 0-65535 | `BANK+0x28` |
| IR 14 | VacT | 0.1 V | 0-65535 | `BANK+0xb6` |

## Where the data comes from

**The USART2 bank — the safety CPU's own grid-voltage measurement**, relayed to
the ARM over USART2 at the offsets above
([`docs/33`](../33-usart2-telemetry-bank.md),
[`docs/wiring/ARM-USART2`](../wiring/ARM-USART2.md)). Not DSP-relayed; the safety
CPU samples the grid independently ([`docs/29`](../29-safety-cpu.md)). IR 13's
offset `BANK+0x28` is also read for generator voltage (IR 121).

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Vgrid` = grid voltage; `VgridL1N`/`VgridL2N` = split-phase L1-N / L2-N voltage.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **IR 12 / 13 / 14 (VacR/S/T):** safety-CPU telemetry — [`arm_sim_contract.py`](../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`grid_r`/`grid_s`/`grid_t`), asserted by `test_safety_cpu_telemetry_reaches_modbus`. Engine read path (regs 12-15 in one read) in [`test_modbus.c`](../../tests/test_modbus.c).
