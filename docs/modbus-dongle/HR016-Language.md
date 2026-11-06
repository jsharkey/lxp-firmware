# HR 16 — Language

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | range |
|---|---|---|
| HR 16 | Language | 0 English, 1 German |

## Side-effects of writing

**Local HMI string set** on the front-panel display. Persisted to config flash;
no inter-processor effect. (Panel: [`docs/wiring/ARM-LCD`](../wiring/ARM-LCD.md).)
