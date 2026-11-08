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

- **DSP config-push (T25/T10):** LINE_MODE is packed into config-frame **block 0 @0x1a** (low byte of DSP `0xAD83`, alongside the EPS voltage-select enum and the 60 Hz bit): value `1` (UPS) sets bit `0x20` (GEN=2 is not dongle-writable in the bare boot, so its bit is unconfirmed). Found by resolving the T25 1-value registers; routing verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH`), encoding locked in [`test_dsp_config.c`](../../../tests/test_dsp_config.c). See the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md).
- **Write validation (T24/T24b):** the whole-HR sweep
  ([`test_wrsem_sweep.py`](../../../tests/test_wrsem_sweep.py) /
  [`wrsem_expected.py`](../../../tests/wrsem_expected.py)) found the factory accepts
  0/1 but **rejects 2 (GEN) and 3** in the bare-boot state (exception 3 — likely
  GEN precondition-gated, docs/31 Q11); ours replicates `[0, 1]`, pinned at the host
  level by [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
