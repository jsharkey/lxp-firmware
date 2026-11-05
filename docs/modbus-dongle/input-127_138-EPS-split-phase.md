# IR 127-138 — EPS split-phase (L1N/L2N)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

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
([`docs/33`](../33-usart2-telemetry-bank.md)). **Powers/energies: ARM-computed /
accumulated.** This is the per-leg detail of the aggregate EPS output at
[`input-020_025-EPS-output`](input-020_025-EPS-output.md).
