# HR 16 — Language

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | range |
|---|---|---|
| HR 16 | Language | 0 English, 1 German |

## Side-effects of writing

**Local HMI string set** on the front-panel display. Persisted to config flash;
no inter-processor effect. (Panel: [`docs/wiring/ARM-LCD`](../wiring/ARM-LCD.md).)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
