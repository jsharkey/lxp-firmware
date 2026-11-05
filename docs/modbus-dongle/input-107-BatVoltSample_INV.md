# IR 107 — BatVoltSample_INV

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | bank offset |
|---|---|---|---|
| IR 107 | BatVoltSample_INV | 0.1 V | `BANK+0x0a` |

## Where the data comes from

**The USART2 bank** (`BANK+0x0a`) — the inverter-side battery-voltage sample,
relayed over USART2 ([`docs/33`](../33-usart2-telemetry-bank.md)). This is the
inverter's *own* measurement of pack voltage, distinct from the BMS-reported pack
voltage and from IR 4 Vbat ([`input-004-Vbat`](input-004-Vbat.md)).
