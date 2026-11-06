# IR 18 — IinvRMS (inverter current RMS)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 18 | IinvRMS | 0.01 A | 0-65535 | `BANK+0x24` |

## Where the data comes from

**The USART2 bank** (`BANK+0x24`), relayed over USART2
([`docs/33`](../33-usart2-telemetry-bank.md)).
