# HR 90-91 — EPS output V/F set

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | values |
|---|---|---|---|
| HR 90 | EPSVoltageSet | 1 V | 208 / 230 / 240 / 277 |
| HR 91 | EPSFreqSet | 1 Hz | 50 / 60 |

## Side-effects of writing

**Off-grid (EPS) output voltage/frequency targets** — persisted to config flash
and pushed to the DSP (which generates the EPS output) in the config snapshot over
USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)).
