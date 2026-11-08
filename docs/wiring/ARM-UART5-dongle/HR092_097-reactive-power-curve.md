# HR 92-97 — reactive-power curve (PF / Q(V)) parameters

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | unit | note |
|---|---|---|---|
| HR 92 | PF/Q(V) lock-in point | — | grid-support curve setpoint |
| HR 93 | PF/Q(V) lock-out point | — | grid-support curve setpoint |
| HR 94-95 | lock-in / lock-out (2nd pair) | — | curve setpoints |
| HR 96 | curve delay | — | enter/exit delay |
| HR 97 | curve delay / param | — | reactive-curve param |

Reactive-power grid-support **curve parameters** — the voltage lock-in / lock-out
points and delays for the PF(P) / Q(V) grid-code response (the reactive counterpart of
the active-power derate curve). They tune *when* the inverter trims power factor or
injects/absorbs reactive power as grid voltage moves, per the configured grid standard.

## Classification / provenance

**Persisted grid-code setpoints, default off (0).** On the canonical 07 image both
the factory and ours read **0** for HR 92-97 in the bare-boot state (no grid-support
curve provisioned) — they are *not* in the T23 "known-diff: no HR default" set, i.e.
the factory's own power-on value is also 0 (see
[`regsweep_expected.py`](../../../tests/regsweep_expected.py); the group is in the
"match" bucket of the [T23 scoreboard](regsweep-scoreboard.md)). Our firmware does not
yet carry these in its persistence map ([`settings_map.h`](../../../include/inv/settings_map.h)),
so they are a **settings-defaults gap** (T03/T12) should a grid standard that uses them
be selected — not a live or computed register. The exact curve encoding is driven by
the selected `OutputStandard` (HR 16 Language / grid-code), a T19/T26 follow-on.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** HR 92-97 are read on both images from one seeded
  state and diffed in [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py) — they land in the
  **match** bucket (ours == factory == 0 at boot). No focused write-semantics/persistence
  vector yet (they are off by default and grid-code-gated); add one with the grid-code
  work if a standard that drives the reactive curve is wired (hand-off).
