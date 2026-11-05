# HR 146 — LineMode

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | values |
|---|---|---|
| HR 146 | LineMode | 0 APL (90-280V 20ms), 1 UPS (170-280V 10ms), 2 GEN (90-280V 20ms) |

## Side-effects of writing

**Input-voltage window / transfer behaviour selector** — persisted to config flash
and pushed to the DSP in the config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)). Governs the AC-input acceptance
window and transfer timing (and relates to generator handling, cf.
[`input-077-ACInputType`](input-077-ACInputType.md)).
