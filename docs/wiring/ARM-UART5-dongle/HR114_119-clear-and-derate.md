# HR 114-119 — ClearFunction + derate / offset settings

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | note |
|---|---|---|
| HR 114 | ClearFunction | command: clear parallel fault code |
| HR 115 | OVFDerate | over-frequency derate start |
| HR 116 | PtoUser | grid→user power limit |
| HR 117 | — | reserved |
| HR 118 | VbatDerate | battery-voltage derate point |
| HR 119 | wCT_PowerOffset | CT power offset (settings `+0x2f`) |

A mixed group: **HR 114 is a command** (write to clear the parallel-system fault
code), the rest are **derate / offset settings** — over-frequency derate start
(HR 115), the grid-to-user power cap (HR 116), the battery-voltage derate knee
(HR 118), and the CT power offset (HR 119). HR 117 is reserved.

## Classification / provenance

- **HR 119 (wCT_PowerOffset)** is persisted — settings `+0x2f` in our map
  ([`settings_map.h`](../../../include/inv/settings_map.h)), default 0.
- **HR 114 (ClearFunction)** is a momentary command (idle 0), not stored.
- **HR 115/116/118** read **0** on both images at bare boot (T23 **match** bucket,
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py)) — default-off derate
  settings the factory also powers up at 0; ours does not yet persist them (a
  settings-defaults follow-on if a grid standard enables the derate).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** HR 119 (wCT_PowerOffset, `+0x2f`) is pinned in the
  shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py))
  and round-trips **cross-image** in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py)
  (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`).
- **Whole-surface parity (T23):** HR 114-119 are read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py) — all in the **match**
  bucket (ours == factory at boot: HR 119 offset 0, the derates off, the command idle).
  Focused vectors (HR 119 persistence; HR 114 clear-fault effect; the derate knees) are
  hand-offs to T03 / the protection-logic work.
