# HR 63 — PowerSoftStartSlope (loading rate)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) register documented under T26.

| reg | name | unit | note |
|---|---|---|---|
| HR 63 | PowerSoftStartSlope | ‰/min | power ramp (soft-start) rate |

The **soft-start loading rate**: how fast the inverter ramps its output power after
start-up or after a disturbance, in per-mille of rated power per minute. A grid-support
parameter (gentle re-connection), sitting just below the grid-code protection block
(HR 25-62) in the map.

## Classification / provenance

**Persisted setting (factory default, ours-gap).** HR 63 shows **"known-diff: no HR
default"** in the T23 sweep ([`regsweep_expected.py`](../../../tests/regsweep_expected.py))
— the factory powers up with a provisioned ramp rate while ours boots `0`, and it is
not yet in our persistence map ([`settings_map.h`](../../../include/inv/settings_map.h)):
a **settings-defaults gap** (T03/T12), not a live/computed register.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** HR 63 is read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py) — a tracked
  **known-diff: no-default** (ours boots 0). Adding it to the T03 `SETTINGS_MAP`
  persistence vectors (and our persistence map) is the follow-on.
