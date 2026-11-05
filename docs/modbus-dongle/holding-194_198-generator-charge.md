# HR 194-198 — generator charge settings

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 194 | GenChgStartVolt | 0.1 V | 384-520 |
| HR 195 | GenChgEndVolt | 0.1 V | 480-590 |
| HR 196 | GenChgStartSOC | % | 0-90 |
| HR 197 | GenChgEndSOC | % | 20-100 |
| HR 198 | MaxGenChgBatCurr | A | 0-60 |

## Side-effects of writing

**Generator-charging thresholds** (valid per HR 120 bit7 GenChargeType: by voltage
vs by SOC). Persisted to config flash and pushed to the DSP in the config snapshot
over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)). Relate to
[`input-077-ACInputType`](input-077-ACInputType.md) and
[`holding-146-LineMode`](holding-146-LineMode.md) (GEN mode).
