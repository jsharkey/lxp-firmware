# HR 112 — SetSystemType

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | values |
|---|---|---|
| HR 112 | SetSystemType | 0 non-parallel, 1 1-phase parallel (master), 2 slave, 3 3-phase parallel (master) |

## Side-effects of writing

**Parallel-system role.** Persisted to config flash; coordinates the
parallel-operation behaviour (reported back on the input side at
[`IR113-ParallelInfo`](IR113-ParallelInfo.md)). Parallel coordination
between inverters uses a CAN bus; a mismatch raises E008/E009/E010
([`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).
**Note space split:** HR 112/113 (settings) vs IR 113 (status).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `Set System Type` = **Not Parallel** | Single Phase Parallel | Three Phase Parallel (configurable only in standby or fault).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **DSP config-push (T10/T25):** SetSystemType is multi-target in the config frame — its bit0 contributes `0x08` to **block 0 @0x1c** (DSP `0xAD84` flags), and it also moves **block 3 @0x19** (not yet emitted by ours). The block-0 contribution's routing is verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH`) and the encoding in [`test_dsp_config.c`](../../../tests/test_dsp_config.c). See the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md).

- **Flash persistence (T03):** HR 112 is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)). (Value 2 = slave is gated/rejected on write — see `SETTINGS_MAP`.)
