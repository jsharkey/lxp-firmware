# HR 105 — EOD (end-of-discharge SOC)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 105 | EOD | % | 10-90 |

## Side-effects of writing

**End-of-discharge SOC cutoff** — persisted to config flash and pushed to the DSP
in the config snapshot over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)).
Related on-grid/EPS EOD variants: HR 120 bit6 OnGridEODType, HR 125
SOCLowLimitForEPSDischg (index-only).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Discharge tab**: `On Grid EOD Volt` (**default 42.0V**). Related Discharge-tab settings: `Discharge Cut-off Volt` (**default 42.0V**, HR 100), `Battery Warning Volt` (**default 44.0V**).
