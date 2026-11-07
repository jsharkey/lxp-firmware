# HR 99-102, 144 — lead-acid charge/discharge

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 99 | ChargeVoltRef | 0.1 V | 500-590 |
| HR 100 | CutVoltForDischg | 0.1 V | 400-500 |
| HR 101 | ChargeCurr | A (¼A) | 0-140 |
| HR 102 | DischgCurr | A (¼A) | 0-140 |
| HR 144 | FloatChargeVolt | 0.1 V | 500-560 |

## Side-effects of writing

**Lead-acid battery charge/discharge parameters.** Used when a non-BMS (lead-acid)
battery is configured. Persisted to config flash and pushed to the DSP (which runs
the charge controller) in the config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)). For BMS (lithium) packs the
equivalent limits are *read from the pack* over CAN1 instead
([`IR081_106-BMS`](IR081_106-BMS.md)).

**`HR 99` also caps the BMS charge voltage (T11a).** Even with a BMS pack, the
served/working charge-V reference is `IR 83 = min(pack 0x351 limit, HR 99)` — so
`ChargeVoltRef` is the ceiling on the pack's own request, not just a lead-acid
setpoint. Its power-on default is **574** (57.4 V, per the LCD note below), which is
what makes an out-of-range pack limit appear to "clamp" at ~57.4 V; writing HR 99
moves that ceiling. See
[`IR081_106-BMS` → Working charge-voltage derivation](IR081_106-BMS.md#working-charge-voltage-derivation-t11a).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab**: `Lead-Acid Charge Voltage` (**default 57.4V**, HR 99), `Lead-Acid Floating Voltage` (**default 54.0V**, HR 144), `Charge Current Limit` (**default 250A**, HR 101), `Discharge Current Limit` (**default 250A**, HR 102).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 101 (ChargeCurr):** write/read-back [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_modbus_charge_current_write_read`; flash persistence `test_settings_persist_across_cold_boot`; cross-image persistence [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py); HMI edit [`test_hmi.c`](../../../tests/test_hmi.c) (`HR_CHARGE_CURR`).
- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — HR 101 `141` (> spec max 140) is **accepted** (cold default also reads `250`): the factory enforces no upper bound ([`docs/31`](../../31-factory-quirks.md) Q6, replicated for parity). Host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
- **HR 99 (ChargeVoltRef):** exercised as the BMS charge-V ceiling (T11a) — `IR 83 = min(0x351, HR 99)`: factory-oracled sim test [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_bms_charge_volt_ref_clamps_to_setting` (+ the two `*telemetry*` tests for the pass-through branch), and the pure-function boundary sweep [`test_bms_limits.c`](../../../tests/test_bms_limits.c).
- **DSP config-push grid-charge slot (T10):** the per-block filler packs these into the ARM→DSP config frame — HR 101 (ChargeCurr)→block 6 @0x17, HR 102 (DischgCurr)→block 6 @0x1b (both A→0.1 A, ×10), HR 99 (ChargeVoltRef)→block 6 @0x25 (0.1 V). Differentially verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH` in [`dsppush_contract.py`](../../../tests/dsppush_contract.py)); see [block-03_06-gridcharge-slots.md](../ARM-USART3-DSP/block-03_06-gridcharge-slots.md).
- **HR 100 (CutVolt) write validation (T24/T24b):** the whole-HR sweep
  ([`test_wrsem_sweep.py`](../../../tests/test_wrsem_sweep.py) /
  [`wrsem_expected.py`](../../../tests/wrsem_expected.py)) found the factory enforces
  `400-499` (rejects the spec's 500); ours replicates it (host boundaries in
  [`test_settings_validate.c`](../../../tests/test_settings_validate.c)). HR 99 is
  validated one-sided (accepts below 500, max 590 — see the sweep).
- **HR 144 (FloatVolt):** the factory rejects *every* probed value in the bare-boot
  state (precondition-gated, docs/31 Q11), so ours stays permissive — a recorded
  `OURS_DEVIATIONS` entry, not yet pinned.
