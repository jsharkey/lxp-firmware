# HR 105 — EOD (end-of-discharge SOC)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 105 | EOD | % | 10-90 |

## Side-effects of writing

**End-of-discharge SOC cutoff** — persisted to config flash and pushed to the DSP
in the config snapshot over USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)).
Related on-grid/EPS EOD variants: HR 120 bit6 OnGridEODType, HR 125
SOCLowLimitForEPSDischg (index-only).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Discharge tab**: `On Grid EOD Volt` (**default 42.0V**). Related Discharge-tab settings: `Discharge Cut-off Volt` (**default 42.0V**, HR 100), `Battery Warning Volt` (**default 44.0V**).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 105 (EOD):** [`test_dsp_config.c`](../../../tests/test_dsp_config.c) sets `HR_EOD` and confirms it is carried in the config push.
- **DSP config-push grid-charge slot (T10):** the per-block filler packs HR 105 (end-of-discharge SOC %) into the ARM→DSP config frame at block 3 @0x1b (single byte). Differentially verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH` in [`dsppush_contract.py`](../../../tests/dsppush_contract.py)); see [block-03_06-gridcharge-slots.md](../ARM-USART3-DSP/block-03_06-gridcharge-slots.md).
- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `50` accepted, `9` (< min 10) rejected with Modbus exception 3, but `91` (> spec max 90) is **accepted** — the factory enforces only the lower bound ([`docs/31`](../../31-factory-quirks.md) Q6, replicated for parity). Host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
- **Flash persistence (T03):** HR 105 is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)).
