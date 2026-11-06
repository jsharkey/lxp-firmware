# HR 23-24 — ConnectTime / ReconnectTime

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| HR 23 | ConnectTime | s | 30-600 | grid connection waiting time |
| HR 24 | ReconnectTime | s | 0-900 | reconnection waiting time |

## Side-effects of writing

**Grid-sync timing for the DSP** — persisted to config flash and pushed to the DSP
in the config snapshot over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)).
Govern how long the unit waits before (re)connecting to the grid.
