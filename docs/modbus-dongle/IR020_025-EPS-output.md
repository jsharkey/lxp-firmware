# IR 20-25 — EPS (off-grid) output

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

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
([`docs/33`](../33-usart2-telemetry-bank.md)). **Powers (IR 24/25) and frequency
(IR 23): ARM-computed/derived.** Split-phase L1N/L2N detail of the same EPS output
is at [`IR127_138-EPS-split-phase`](IR127_138-EPS-split-phase.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **UPS tab**: `Veps` = load voltage, `Feps` = load frequency, `VepsL1N`/`VepsL2N` = L1-N/L2-N load voltage, `Peps` = active power of load, `Seps` = apparent power of load.
