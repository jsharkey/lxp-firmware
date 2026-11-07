# HR 25-62 — grid-code protection + reactive

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

Large block (set per grid code). Groups:

- **25-28** GridVolt/FreqConnLow/High — allowed grid connection V/F range.
- **29-41** GridVoltLimit1/2/3 Low/High + times, GridVoltMovAvgHigh — over/under-
  voltage protection points & times (levels 1-3).
- **42-53** GridFreqLimit1/2/3 Low/High + times — over/under-frequency protection.
- **54-58** MaxQPercentForQV, V1L/V2L/V1H/V2H — Q(V) curve points.
- **59** ReactivePowerCMDType (0-7), **60** ActivePowerPercentCMD (%),
  **61** ReactivePowerPercentCMD (%), **62** PFCMD (0.001).

Units/ranges "according to grid regulation"; see spec pages 15-17 for each.

## Side-effects of writing

**Grid-protection & reactive-power configuration for the DSP.** These define the
protection curves the real-time power FSM enforces, so they are persisted to
config flash and pushed to the DSP in the config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)/[`docs/10`](../../10-dsp-config-field-map.md)).
The ARM stores/forwards them; the DSP acts on them. Related reactive-curve
lock-in/out params are HR 92-97 (index-only). **Open:** per-field offsets in the
DSP config block (the field-level map in [`docs/10`](../../10-dsp-config-field-map.md)
is still being completed).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** the grid-protection registers pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py) — HR 25-40, 43-49, 51-53, 59-61 of this range) round-trip **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)). Registers in this range not in `SETTINGS_MAP` (e.g. HR 62) have no persistence test.
