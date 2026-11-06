# HR 15 — Com Addr (Modbus slave address)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | range |
|---|---|---|
| HR 15 | Com Addr | 0-150 |

## Side-effects of writing

**Changes the ARM's own Modbus slave address on the dongle bus** — the `addr`
byte the dongle must use to reach this inverter. Persisted to config flash.
Self-referential: after a successful write the inverter answers on the new
address.
