# HR 147-148 — battery capacity / nominal voltage

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| HR 147 | Battery capacity | Ah | 0-10000 | for unmatched batteries |
| HR 148 | Battery nominal Voltage | 0.1 V | 400-590 | for unmatched batteries |

## Side-effects of writing

**Manual battery parameters for "unmatched" (non-BMS) packs** — persisted to
config flash and used by the charge/discharge control (pushed to the DSP in the
config snapshot). For BMS packs these come from the pack over CAN1 instead
([`IR081_106-BMS`](IR081_106-BMS.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** HR 147 (BatCapacity) is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)). HR 148 (BatNominalVolt) is not pinned — no test yet.
