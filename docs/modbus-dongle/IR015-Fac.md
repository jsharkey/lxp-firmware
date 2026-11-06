# IR 15 — Fac (grid frequency)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 15 | Fac | 0.01 Hz | 0-65535 | `BANK+0x5e` |

## Where the data comes from

**The USART2 bank** (`BANK+0x5e`) — the safety CPU's own grid-frequency
measurement, relayed over USART2 ([`docs/33`](../33-usart2-telemetry-bank.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Fgrid` = grid frequency.
