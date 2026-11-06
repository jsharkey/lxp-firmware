# IR 107 — BatVoltSample_INV

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | bank offset |
|---|---|---|---|
| IR 107 | BatVoltSample_INV | 0.1 V | `BANK+0x0a` |

## Where the data comes from

**The USART2 bank** (`BANK+0x0a`) — the inverter-side battery-voltage sample,
relayed over USART2 ([`docs/33`](../33-usart2-telemetry-bank.md)). This is the
inverter's *own* measurement of pack voltage, distinct from the BMS-reported pack
voltage and from IR 4 Vbat ([`IR004-Vbat`](IR004-Vbat.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `Vbat_Inv` = inverter sampling battery voltage (the inverter's own measurement, vs the BMS-reported pack voltage).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
