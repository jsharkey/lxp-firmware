# HR 22 — StartPVVolt (PV start voltage)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 22 | StartPVVolt | 0.1 V | 900-5000 |

## Side-effects of writing

**A DSP power-stage setting** — the PV voltage at which the inverter begins
working. Persisted to config flash and pushed to the DSP in the config snapshot
over USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)/[`docs/10`](../../10-dsp-config-field-map.md),
[`docs/wiring/ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md)); the ARM does not act on it
itself. **Open:** exact byte offset in the DSP config block.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Write probe (T04):** on `ceaa-07xx_vE_260214.bin` a func-`0x06` write to HR 22 returns
  Modbus exception 2 (ILLEGAL_ADDRESS) for any value and a read returns `65` — the
  register appears unimplemented/remapped on this image. Recorded as
  [`docs/31`](../../31-factory-quirks.md) **Q7**; not asserted in the common
  write-semantics test (ours implements HR 22, so the two intentionally differ).
