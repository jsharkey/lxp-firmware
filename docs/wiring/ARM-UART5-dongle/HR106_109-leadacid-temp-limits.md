# HR 106-109 — lead-acid temperature limits

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | unit | settings offset (ours) |
|---|---|---|---|
| HR 106 | TemprLowerLimitDischg | 0.1 °C | (factory-persisted; not in ours) |
| HR 107 | TemprUpperLimitDischg | 0.1 °C | `+0xa1` |
| HR 108 | TemprLowerLimitChg | 0.1 °C | (factory-persisted; not in ours) |
| HR 109 | TemprUpperLimitChg | 0.1 °C | `+0xa5` |

The **lead-acid battery temperature window** — the lower/upper limits for discharge
(HR 106/107) and charge (HR 108/109). Outside the window the inverter inhibits the
corresponding battery operation (a lead-acid protection; lithium packs report their
own limits over the BMS CAN).

## Classification / provenance

**Persisted settings.** HR 107 (`+0xa1`) and HR 109 (`+0xa5`) are in our persistence
map ([`settings_map.h`](../../../include/inv/settings_map.h)) and survive a cold boot;
their offsets were pinned by the T03 probe (the docs/23 note "+0xa4 was wrong" for
HR 109 is corrected here to `+0xa5`). HR 106 shows **"known-diff: no HR default"** in
the T23 sweep ([`regsweep_expected.py`](../../../tests/regsweep_expected.py)) — the
factory powers up with a provisioned default while ours boots `0`, so HR 106 (and its
charge-side twin HR 108) are a **settings-defaults gap** in ours (T03/T12): the factory
persists all four, ours currently persists only the two upper limits.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** HR 107 (`+0xa1`) and HR 109 (`+0xa5`) are pinned in the
  shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py))
  and round-trip **cross-image** in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py)
  (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`).
- **Whole-surface parity (T23):** HR 106-109 are read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py): HR 106 is a tracked
  **known-diff: no-default** (ours boots 0), HR 107-109 match once seeded. Adding HR
  106/108 to the persistence map is the follow-on that closes the lower-limit defaults gap.
