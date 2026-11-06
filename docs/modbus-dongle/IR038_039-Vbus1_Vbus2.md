# IR 38-39 — Vbus1 / Vbus2

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 38 | Vbus1 | 0.1 V | 0-65535 | `BANK+0x0e` |
| IR 39 | Vbus2 | 0.1 V | 0-65535 | `BANK+0x10` |

## Where the data comes from

**The USART2 bank** at the offsets above, relayed over USART2
([`docs/33`](../33-usart2-telemetry-bank.md)). Half-bus voltage is a separate
register — [`IR120-VBusP`](IR120-VBusP.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **Other tab**: `Vbus1` = voltage of BUS1, `Vbus2` = voltage of BUS2.
