# HR 145 — OutputPrioConfig (output priority)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | values |
|---|---|---|
| HR 145 | OutputPrioConfig | 0 bat-first, 1 PV-first, 2 AC-first |

## Side-effects of writing

**Pushed to the DSP — this is one of the few config bytes whose DSP offset is
pinned.** Output priority lands at **frame offset `0x1E`** of config block 0 in the
ARM→DSP type-1 push over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)/[`docs/10`](../../10-dsp-config-field-map.md),
[`docs/wiring/ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md)). Persisted to config flash and
forwarded to the DSP, which enacts the priority.

## Nuance

The value `2` here = **AC-first output priority**. Unrelated to `State == 2`
(Programming) — an earlier relay-gating draft confused the two; corrected in
[`docs/18`](../../18-power-path-relays.md). The AC-First *time windows* (when AC-first
applies) are separate — [`HR152_157-ACFirst-windows`](HR152_157-ACFirst-windows.md).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 145 (OutputPrioConfig):** [`test_dsp_config.c`](../../../tests/test_dsp_config.c) sets `HR_OUTPUT_PRIO_CFG` (AC-First=2 / PV-First=1) and checks it lands in the config payload.
