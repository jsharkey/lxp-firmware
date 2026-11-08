# IR 127-138 — EPS split-phase (L1N/L2N)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | source |
|---|---|---|---|
| IR 127 | EPSVoltL1N | 0.1 V | USART2 bank `BANK+0x30` |
| IR 128 | EPSVoltL2N | 0.1 V | USART2 bank `BANK+0x32` |
| IR 129-130 | Peps_L1N / L2N | 1 W | ARM-computed |
| IR 131-132 | Seps_L1N / L2N | 1 VA | ARM-computed |
| IR 133-134 | EepsL1N/L2N_day | 0.1 kWh | ARM-accumulated |
| IR 135-138 | EepsL1N/L2N_all L/H | 0.1 kWh | ARM-accumulated (32-bit) |

## Where the data comes from

**Voltages (IR 127/128): the USART2 bank** at `BANK+0x30`/`+0x32`
([`docs/33`](../../33-usart2-telemetry-bank.md)). **Powers/energies: ARM-computed /
accumulated.** This is the per-leg detail of the aggregate EPS output at
[`IR020_025-EPS-output`](IR020_025-EPS-output.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **UPS tab**: `VepsL1N`/`VepsL2N` (L1-N/L2-N load voltage), `PepsL1N`/`PepsL2N` (active power), `SepsL1N`/`SepsL2N` (apparent power), `EepsL1N_day`/`EepsL1N_all`, `EepsL2N_day`/`EepsL2N_all`.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 127 / 128 (EPSVoltL1N / L2N):** live safety-bank mirrors (`+0x30` / `+0x32`),
  served verbatim. In the shared `SAFETY_TELEMETRY` contract
  ([`arm_sim_contract.py`](../../../tests/arm_sim_contract.py)) and asserted ours==factory
  by `test_safety_cpu_telemetry_reaches_modbus` and the per-image
  `test_arm_sim_self_only.py` / `test_arm_sim_factory_only.py` sweeps (T27). Our
  firmware serves them from the bank in [`safety_cpu.c`](../../../src/safety/safety_cpu.c)
  (`PUT(IR_EPS_VOLT_L1N/L2N, +0x30/+0x32)`); verified on ceaa-07xx.
- **IR 129-138 (Peps / Seps / Eeps L1N/L2N):** ARM-computed / accumulated per leg —
  like the gen power/energy (IR 123-125), these need the EPS power path + accumulator
  exercised, not reachable through telemetry ingest alone. A characterized hand-off.
