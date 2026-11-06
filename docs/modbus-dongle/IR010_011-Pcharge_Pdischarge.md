# IR 10-11 — Pcharge / Pdischarge

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 10 | Pcharge | 1 W | 0-65535 | incoming battery power |
| IR 11 | Pdischarge | 1 W | 0-65535 | outflow battery power |

## Where the data comes from

**ARM-computed battery power** (sign split into charge vs discharge). Derived from
battery voltage × current inside the ARM's telemetry computation, alongside the
other `P*` powers ([`docs/22`](../22-arm-dsp-core-split.md)); not a verbatim bank
field. **Open:** pin the exact current source (BMS CAN vs bank sample).

## On the LCD (EG4 12000XP manual)

DATA MENU **Battery tab**: `Pchg` = battery charge power, `Pdischg` = battery discharge power.
