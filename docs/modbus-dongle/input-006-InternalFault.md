# IR 6 — InternalFault (internal DTC)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range |
|---|---|---|---|
| IR 6 | InternalFault | — | 0-65535 |

## Where the data comes from

**The USART2 bank**, `BANK+0xc8`, combined with an ARM-local DTC byte
(`STATUS+0x91`) before it is served ([`docs/33`](../33-usart2-telemetry-bank.md)).
A diagnostic/trouble code distinct from the main fault bitfield (IR 60/61 — see
[`input-060_063-FaultCode_WarningCode`](input-060_063-FaultCode_WarningCode.md)).
