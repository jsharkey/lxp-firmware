# IR 120 — VBusP (half-bus voltage)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | bank offset |
|---|---|---|---|
| IR 120 | VBusP | 0.1 V | `BANK+0x12` |

## Where the data comes from

**The USART2 bank** (`BANK+0x12`), relayed over USART2
([`docs/33`](../33-usart2-telemetry-bank.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Other tab**: `VbusP` = positive BUS voltage (`VbusN` = negative BUS voltage).
