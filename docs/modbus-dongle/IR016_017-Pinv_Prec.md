# IR 16-17 — Pinv / Prec

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 16 | Pinv | 1 W | 0-65535 | inverter output power (grid port) |
| IR 17 | Prec | 1 W | 0-65535 | AC-charging rectified power |

## Where the data comes from

**ARM-computed** power values (part of the derived `P*` telemetry,
[`docs/22`](../22-arm-dsp-core-split.md)), not verbatim bank fields.
