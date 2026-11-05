# IR 4 — Vbat (battery voltage)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 4 | Vbat | 0.1 V | 0-65535 |

## Where the data comes from

**Not yet pinned to a specific source.** Two candidates, both internal to the
ARM: the inverter-side battery sample on the USART2 bank (cf.
[`input-107-BatVoltSample_INV`](input-107-BatVoltSample_INV.md), `BANK+0x0a`), and
the BMS pack voltage over CAN1 ([`docs/20`](../20-battery-bms-firmware.md)). The
register-getter sweep in [`docs/33`](../33-usart2-telemetry-bank.md) did **not**
map IR 4 to a bank offset, so it is likely assembled/selected in ARM logic.
**Open:** trace the IR 4 getter.
