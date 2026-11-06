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
[`IR077-ACInputType`](IR077-ACInputType.md) and
[`HR146-LineMode`](HR146-LineMode.md) (GEN mode).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab → Generator Setting**: `Generator Charge Type` (Use Vol | **Use SOC**, HR 120 bit), `Gen Charge Start Bat Volt` (**default 46.4V**, HR 194), `Gen Charge End Bat Volt` (~48V, HR 195), `Gen Charge Start Bat SOC` (**default 20%**, HR 196), `Gen Charge End Bat SOC` (**default 100%**, HR 197), gen charge current (**default 30A**, HR 198). The manual also shows `Max. Gen Input Power` (**default 15000W**) — a separate register, not in this 194-198 set.
