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
