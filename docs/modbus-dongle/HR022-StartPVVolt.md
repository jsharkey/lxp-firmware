# HR 22 — StartPVVolt (PV start voltage)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 22 | StartPVVolt | 0.1 V | 900-5000 |

## Side-effects of writing

**A DSP power-stage setting** — the PV voltage at which the inverter begins
working. Persisted to config flash and pushed to the DSP in the config snapshot
over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)/[`docs/10`](../10-dsp-config-field-map.md),
[`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md)); the ARM does not act on it
itself. **Open:** exact byte offset in the DSP config block.
