# HR 146 — LineMode

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | values |
|---|---|---|
| HR 146 | LineMode | 0 APL (90-280V 20ms), 1 UPS (170-280V 10ms), 2 GEN (90-280V 20ms) |

## Side-effects of writing

**Input-voltage window / transfer behaviour selector** — persisted to config flash
and pushed to the DSP in the config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)). Governs the AC-input acceptance
window and transfer timing (and relates to generator handling, cf.
[`IR077-ACInputType`](IR077-ACInputType.md)).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `AC Input Range` = UPS (170-280) | **APL (90-280)** (**default APL**). APL/UPS map to the line-mode options; transfer is slower under APL.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._
