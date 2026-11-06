# IR 19 — PF (power factor)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | bank offset |
|---|---|---|---|---|
| IR 19 | PF | 0.001 | 0-2000 | `BANK+0xaa` |

**Encoding (spec):** `PF ∈ (0,1000] → x/1000`; `PF ∈ (1000,2000) → (1000-x)/1000`
(the upper half encodes the leading/capacitive sign).

## Where the data comes from

**The USART2 bank** (`BANK+0xaa`), relayed over USART2
([`docs/33`](../33-usart2-telemetry-bank.md)).
