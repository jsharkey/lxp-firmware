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

## The generator-charge start/stop gate (T16)

The start/stop decision is **ARM-evaluated** (not left to the DSP): the factory
evaluator `sub_08035050` latches a "charge from generator now" verdict with a
**voltage hysteresis in the charge direction** — start when the battery is low, stop
when it is high — the mirror of the discharge gate ([`HR064-089`](../ARM-UART5-dongle/)
discharge, T15). Reverse-engineered on the canonical 07 image
(`ceaa-07xx_vE_260214.bin`) as the self-contained block `0x08035086 … 0x080350dc`,
verdict byte `0x2000dbc0`:

```
v = (uint16 safety-bank battery voltage @+0x0a) / 10      # signed divide
if (!active) active = (v <  start_v)                       # start charging when LOW
else         active = !(v >= end_v && stop_ok)             # stop only when HIGH *and* confirmed
```

- `start_v` = **HR 194** GenChgStartVolt, settings `+0xac` (0.1 V).
- `end_v`   = **HR 195** GenChgEndVolt, settings `+0xae` (0.1 V).
- The battery voltage is the safety/DSP telemetry bank word at `bank+0x0a` (0.1 V),
  zero-extended then **signed-divided by 10** before the signed compare — reproduce
  that exact divide, not a float.
- **`stop_ok`** gates the turn-OFF: the generator keeps charging past `end_v` until
  the system confirms it is safe to drop it — two DSP/safety-bank status bits,
  `bank+0xb6` **bit 11** AND `bank+0xbc` **bit 15**. Without the confirmation the
  gate stays latched ON even above `end_v`.
- **Mode select:** HR 120 **bit 7** GenChargeType (settings `+0x33` bit 7). `0` = by
  voltage (this gate); `1` = by SOC — the SOC sibling path (HR 196/197, settings
  `+0xb0` packed), a separate verdict byte `0x2000dbc1`. (SOC path RE is a hand-off.)

Settings provenance pinned dynamically (ModbusDsp boot + dongle writes): HR 194 →
`+0xac`, HR 195 → `+0xae`, HR 196/197 → `+0xb0` (packed). The same thresholds are
*also* pushed to the DSP config (block 6, see Test coverage) — that is the DSP's copy
for its own limiting, distinct from this ARM start/stop latch.

Our firmware reimplements the decision as the pure, host-testable
[`inv_gen_charge_volt_gate()`](../../../include/inv/gen_charge.h)
([`src/sched/gen_charge.c`](../../../src/sched/gen_charge.c)); the caller holds the
latch and supplies the bank voltage, the two thresholds and the `stop_ok`
confirmation.

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab → Generator Setting**: `Generator Charge Type` (Use Vol | **Use SOC**, HR 120 bit), `Gen Charge Start Bat Volt` (**default 46.4V**, HR 194), `Gen Charge End Bat Volt` (~48V, HR 195), `Gen Charge Start Bat SOC` (**default 20%**, HR 196), `Gen Charge End Bat SOC` (**default 100%**, HR 197), gen charge current (**default 30A**, HR 198). The manual also shows `Max. Gen Input Power` (**default 15000W**) — a separate register, not in this 194-198 set.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Generator-charge start/stop gate (T16):** the voltage hysteresis above (HR 194
  start-V → settings `+0xac`, HR 195 end-V → `+0xae`; start when `v < start_v`, stop
  when `v >= end_v` **and** `stop_ok`). The factory block `0x08035086…0x080350dc`
  (verdict `0x2000dbc0`) is driven in isolation on the canonical 07 image and checked
  against the shared spec in [`test_gen_charge.py`](../../../tests/test_gen_charge.py)
  `test_factory_matches_spec` / `test_factory_stop_needs_confirm` (`VECTORS` + the
  `stop_ok` DSP-confirm bits in [`gen_charge_contract.py`](../../../tests/gen_charge_contract.py)).
  Our pure `inv_gen_charge_volt_gate()` is held to the **same** vectors by the
  toolchain-free host test [`test_gen_charge.c`](../../../tests/test_gen_charge.c)
  (parity by contract).
- **DSP config-push (T10/T25):** the generator-charge parameters are packed into the ARM→DSP config frame, **block 6**: HR 194 start-V → `0x1d` (BE16, 0.1 V, clamped < end-V), HR 195 end-V → `0x1f` (BE16, 0.1 V), HR 196 start-SOC → `0x21` (u8 %), HR 197 end-SOC → `0x22` (u8 %), HR 198 max-charge-curr → `0x23` (BE16, A→0.1 A). Differentially pinned (single-write, fresh captures) and reproduced byte-for-byte by our firmware, verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH` in [`dsppush_contract.py`](../../../tests/dsppush_contract.py)); see the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md) and [block-03_06](../ARM-USART3-DSP/block-03_06-gridcharge-slots.md).
- **Write validation (T24/T24b):** the whole-HR sweep
  ([`test_wrsem_sweep.py`](../../../tests/test_wrsem_sweep.py) /
  [`wrsem_expected.py`](../../../tests/wrsem_expected.py)) pinned the factory's enforced
  ranges — HR 194 `384-519` (rejects the spec's 520), 195 `480-590`, 196 `1-90`
  (rejects 0), 197 `20-100`, 198 `≥1` one-sided (rejects 0, accepts above the spec's
  60); ours replicates them (host boundaries in
  [`test_settings_validate.c`](../../../tests/test_settings_validate.c)).
