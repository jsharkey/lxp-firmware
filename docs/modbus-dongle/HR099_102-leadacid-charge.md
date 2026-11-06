# HR 99-102, 144 — lead-acid charge/discharge

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 99 | ChargeVoltRef | 0.1 V | 500-590 |
| HR 100 | CutVoltForDischg | 0.1 V | 400-500 |
| HR 101 | ChargeCurr | A (¼A) | 0-140 |
| HR 102 | DischgCurr | A (¼A) | 0-140 |
| HR 144 | FloatChargeVolt | 0.1 V | 500-560 |

## Side-effects of writing

**Lead-acid battery charge/discharge parameters.** Used when a non-BMS (lead-acid)
battery is configured. Persisted to config flash and pushed to the DSP (which runs
the charge controller) in the config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)). For BMS (lithium) packs the
equivalent limits are *read from the pack* over CAN1 instead
([`IR081_106-BMS`](IR081_106-BMS.md)).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab**: `Lead-Acid Charge Voltage` (**default 57.4V**, HR 99), `Lead-Acid Floating Voltage` (**default 54.0V**, HR 144), `Charge Current Limit` (**default 250A**, HR 101), `Discharge Current Limit` (**default 250A**, HR 102).
