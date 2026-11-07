# HR 194-198 — generator charge settings

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 194 | GenChgStartVolt | 0.1 V | 384-520 |
| HR 195 | GenChgEndVolt | 0.1 V | 480-590 |
| HR 196 | GenChgStartSOC | % | 0-90 |
| HR 197 | GenChgEndSOC | % | 20-100 |
| HR 198 | MaxGenChgBatCurr | A | 0-60 |

## Side-effects of writing

**Generator-charging thresholds** (valid per HR 120 bit7 GenChargeType: by voltage
vs by SOC). Persisted to config flash and pushed to the DSP in the config snapshot
over USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)). Relate to
[`IR077-ACInputType`](IR077-ACInputType.md) and
[`HR146-LineMode`](HR146-LineMode.md) (GEN mode).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab → Generator Setting**: `Generator Charge Type` (Use Vol | **Use SOC**, HR 120 bit), `Gen Charge Start Bat Volt` (**default 46.4V**, HR 194), `Gen Charge End Bat Volt` (~48V, HR 195), `Gen Charge Start Bat SOC` (**default 20%**, HR 196), `Gen Charge End Bat SOC` (**default 100%**, HR 197), gen charge current (**default 30A**, HR 198). The manual also shows `Max. Gen Input Power` (**default 15000W**) — a separate register, not in this 194-198 set.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **DSP config-push (T10/T25):** the generator-charge parameters are packed into the ARM→DSP config frame, **block 6**: HR 194 start-V → `0x1d` (BE16, 0.1 V, clamped < end-V), HR 195 end-V → `0x1f` (BE16, 0.1 V), HR 196 start-SOC → `0x21` (u8 %), HR 197 end-SOC → `0x22` (u8 %), HR 198 max-charge-curr → `0x23` (BE16, A→0.1 A). Differentially pinned (single-write, fresh captures) and reproduced byte-for-byte by our firmware, verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH` in [`dsppush_contract.py`](../../../tests/dsppush_contract.py)); see the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md) and [block-03_06](../ARM-USART3-DSP/block-03_06-gridcharge-slots.md).
- **Write validation (T24/T24b):** the whole-HR sweep
  ([`test_wrsem_sweep.py`](../../../tests/test_wrsem_sweep.py) /
  [`wrsem_expected.py`](../../../tests/wrsem_expected.py)) pinned the factory's enforced
  ranges — HR 194 `384-519` (rejects the spec's 520), 195 `480-590`, 196 `1-90`
  (rejects 0), 197 `20-100`, 198 `≥1` one-sided (rejects 0, accepts above the spec's
  60); ours replicates them (host boundaries in
  [`test_settings_validate.c`](../../../tests/test_settings_validate.c)).
