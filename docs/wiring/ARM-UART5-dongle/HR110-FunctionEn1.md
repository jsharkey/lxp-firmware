# HR 110 — FunctionEn1 (bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| bit | field | note |
|---|---|---|
| 0 | ubPVGridOffEn | 0 disable / 1 enable |
| 1 | ubFastZeroExport | |
| 2 | ubMicroGridEn | |
| 3 | ubBatShared | |
| 4 | ubChgLastEn | |
| 5-6 | CTSampleRatio | 0: 1/1000, 1: 1/3000 |
| 12-13 | PVCTSampleRatio | 0: 1/1000, 1: 1/3000 |

## Side-effects of writing

**Secondary feature-enable word** incl. CT (current-transformer) sample ratios —
persisted to config flash and pushed to the DSP in the config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)). The CT ratios affect how metering
currents are scaled. (A further `uFunctionEn2` word is HR 179, index-only.)

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `PV Grid Off` (**default Disable**) = `ubPVGridOffEn` (bit 0). `Battery Shared` (**default Disabled**) is the parallel battery-sharing enable.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **DSP config-push (T10/T25):** FunctionEn1 is bit-remapped into config-frame **block 0 @0x1c** (low byte of the DSP `0xAD84` flags word, over a `0x02` base): bit0→`0x80`, bit7→`0x10`, bit10→`0x20` (factory-decoded). (The AC-charge-enable bit `0x08` comes from HR 112 `SET_SYSTEM_TYPE` bit0, not FunctionEn1.) Routing verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH`). Note: `0x1c` also carries a `0x02` "FuncEn-not-configured" latch that the factory clears on the first HR 21 write; ours is always configured so it omits `0x02`, making `0x1c` byte-exact ours==factory in the configured state. See the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md) and [block-00](../ARM-USART3-DSP/block-00-output-priority.md).

- **Flash persistence (T03):** HR 110 is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)).
