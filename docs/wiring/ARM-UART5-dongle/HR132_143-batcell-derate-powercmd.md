# HR 132-143 — BatCell limits / derate / high-res power commands

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | note |
|---|---|---|
| HR 132-134 | BatCell limits | per-cell voltage limits / derate |
| HR 135-136 | derate params | |
| HR 137 | SpecLoadCompensate | special-load compensation |
| HR 138-143 | *PowerPercentCMD (0.1 %) | high-res variants of HR 60 / 64-66 / 74 / 82 |

Two sub-groups: **HR 132-137** are battery-cell limit / derate / special-load
compensation settings, and **HR 138-143** are the **0.1 %-resolution** variants of the
active/reactive power-percent commands already exposed at coarser resolution on
HR 60 (ActivePowerPercentCMD) and HR 64-66 / 74 / 82 — i.e. finer-grained duplicates
of the packed power-command block (`settings_map.h` slot 5).

## Classification / provenance

- **HR 133** shows **"known-diff: no HR default"** in the T23 sweep
  ([`regsweep_expected.py`](../../../tests/regsweep_expected.py)) — a factory-provisioned
  default vs ours booting `0` (settings-defaults gap, T03/T12).
- **HR 132, 134-137** read `0` on both images at bare boot (T23 **match** bucket) —
  default-off cell-limit / derate settings.
- **HR 138-143 (hi-res PowerPercentCMD)** are **command** registers (the 0.1 %
  variants of the slot-5 power commands), idle `0` on both; they mirror the coarse
  commands at HR 60 / 64-66 / 74 / 82 (see [`HR145-OutputPrioConfig`](HR145-OutputPrioConfig.md)
  and the packed power-command block in [`settings_map.h`](../../../include/inv/settings_map.h)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** HR 132-143 are read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py): HR 133 is a tracked
  **known-diff: no-default**, the rest **match** at 0. Focused vectors (HR 133
  persistence; the hi-res power commands vs their coarse twins) are hand-offs to T03 /
  the power-command work.
