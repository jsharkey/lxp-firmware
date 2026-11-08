# HR 149-151 — lead-acid equalization

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | unit | settings offset (ours) |
|---|---|---|---|
| HR 149 | EqualizationVolt | 0.1 V | (factory-persisted; not in ours) |
| HR 150 | EqualizationInterval | day | (factory-persisted; not in ours) |
| HR 151 | EqualizationTime | min | `+0x7c` |

The **lead-acid equalization charge** parameters: the equalization target voltage
(HR 149), how often an equalization cycle runs (HR 150, in days), and how long it lasts
(HR 151, in minutes). Equalization is a periodic controlled overcharge that balances
flooded/lead-acid cells; lithium packs ignore it.

## Classification / provenance

**Persisted settings.** HR 151 (EqualizationTime, `+0x7c`) is in our persistence map
([`settings_map.h`](../../../include/inv/settings_map.h)) and the shared persistence
contract. HR 149 and HR 150 show **"known-diff: no HR default"** in the T23 sweep
([`regsweep_expected.py`](../../../tests/regsweep_expected.py)) — the factory powers up
with provisioned equalization voltage/interval while ours boots `0`, a
**settings-defaults gap** (ours persists only the time).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** HR 151 (EqualizationTime, `+0x7c`) is pinned in the
  shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py))
  and round-trips **cross-image** in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py)
  (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`).
- **Whole-surface parity (T23):** HR 149-151 are read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py): HR 149/150 are tracked
  **known-diff: no-default** (ours boots 0), HR 151 round-trips. Adding HR 149/150 to
  the persistence map closes the remaining equalization defaults gap.
