# HR 103 — MaxBackFlow (feed-in limit)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | unit | note |
|---|---|---|---|
| HR 103 | MaxBackFlow | % | feed-in grid power set |

## Side-effects of writing

**Export/feed-in power cap** — persisted to config flash and pushed to the DSP
(which limits export) in the config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
