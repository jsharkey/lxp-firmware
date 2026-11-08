# HR 121-125 — Q2_QV / OVFDerateEnd / SOCLowLimitForEPS

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | note |
|---|---|---|
| HR 121 | Q2_QV | reactive-curve Q(V) second setpoint |
| HR 122-123 | — | reserved |
| HR 124 | OVFDerateEnd | over-frequency derate end point |
| HR 125 | SOCLowLimitForEPS | EPS (off-grid) low-SOC cutoff |

Three grid-support / EPS settings interleaved with two reserved slots: a second
reactive Q(V) curve setpoint (HR 121, the companion of the HR 92-97 reactive curve),
the over-frequency derate **end** point (HR 124, paired with HR 115 `OVFDerate`
start), and the **EPS low-SOC limit** (HR 125) — the state-of-charge floor below which
the off-grid/EPS output is cut.

## Classification / provenance

- **HR 125 (SOCLowLimitForEPS)** shows **"known-diff: no HR default"** in the T23 sweep
  ([`regsweep_expected.py`](../../../tests/regsweep_expected.py)) — the factory powers
  up with a provisioned EPS SOC floor while ours boots `0`: a **settings-defaults gap**
  (T03/T12). It is a persisted setting on the factory.
- **HR 121 (Q2_QV)** and **HR 124 (OVFDerateEnd)** read `0` on both images at bare boot
  (T23 **match** bucket) — default-off grid-support params, not yet in our persistence
  map.
- **HR 122-123** are reserved (no register in the published map).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** HR 121-125 are read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py): HR 125 is a tracked
  **known-diff: no-default** (ours boots 0), HR 121/124 match at 0. Adding HR 125 to the
  T03 persistence vectors (EPS low-SOC floor) is the natural follow-on.
