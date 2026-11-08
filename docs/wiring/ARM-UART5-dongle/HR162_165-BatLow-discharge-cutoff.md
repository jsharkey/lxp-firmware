# HR 162-165 — battery-undervoltage (discharge) cut-off + recovery

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | spec range | factory dongle |
|---|---|---|---|---|
| HR 162 | BatLowVoltage | 0.1 V | 400-500 | **writable, 420-560** |
| HR 163 | BatLowBackVoltage | 0.1 V | 420-520 | **not writable (exc 2)** |
| HR 164 | BatLowSOC | % | 0-90 | **writable, 15-100** |
| HR 165 | BatLowBackSOC | % | 20-100 | **not writable (exc 2)** |

These are the **battery-undervoltage (discharge) cut-off** points (`BatLow*`) and
their **recovery / resume** points (`BatLowBack*`) — the register backing for the
07-series changelog item **#6/#7 "Configurable Discharge Resume SOC (+5 % / +2 V)"**
([`docs/11`](../../11-12000xp-revisions.md), T17). The device stops battery discharge
when the battery falls to the cut-off (`BatLow`) and resumes once it recovers to the
higher recovery point (`BatLowBack`) — a deadband, the discharge sibling of the
generator-charge hysteresis in [`HR194_198`](HR194_198-generator-charge.md). Which
pair is active is selected by **DischgCtrlType** (HR 120 bits 4-5: 0 by voltage, 1 by
SOC, 2 both — see [`HR120`](HR120-SysEnable.md)), per the EG4 spec ("DisChgCtrl selects
according to voltage or SOC or both").

## Side-effects of writing

The two **cut-off** registers are dongle-writable and land in the ARM settings struct
(`0x2000c85c`): **HR 162 → settings `+0x7e`** (u16), **HR 164 → settings `+0x86`**
(u16). Pinned black-box by writing over the dongle and reading the struct back (T17).

### The dongle rejects the two *recovery* registers (T17)

On the canonical 07 image (`ceaa-07xx_vE_260214`), a `0x06` write to **HR 163** or
**HR 165** is answered with **exception 2 (ILLEGAL_ADDRESS) for every value** — tested
across the whole spec range and across all four DischgCtrlType modes (0/1/2/3), none
of which opens them. So the *configurable discharge-resume thresholds are HMI-only on
this firmware's dongle*; only the cut-off points (162/164) can be set over Modbus.
Their cut-off siblings answer normally, so this is a per-register property of the
write dispatch, not a dead block. (Raw reply: `… func|0x80 … reg 0x00a3/0x00a5 02`.)

### Factory dongle bounds ≠ the published spec

Black-box boundary sweep (fresh boot per value, T17): **HR 162** accepts `[420, 560]`
(0.1 V) — rejecting the spec's low end (400-419) and accepting above the spec's 500 up
to 560; **HR 164** accepts `[15, 100]` (%). Out-of-range writes draw exception 3
(ILLEGAL_VALUE), like every other ranged register. These are the *enforced* bounds, as
with the several other spec-vs-actual gaps catalogued in
[`docs/31`](../../31-factory-quirks.md) Q6/Q11 (and the write handler confirmed HR
158-161 against their spec in the same sweep, so the numbering is anchored).

**Not yet pinned (hand-off):** whether HR 162/164 persist to the config flash (and at
what slot offset), and the ARM discharge-resume *control* path that consumes them (it
runs in the RTOS main loop, not reachable by injecting a dongle write — the same limit
the relay/gate RE hit, [`docs/19`](../../19-gpio-test-harness.md)). The discharge
voltage/SOC hysteresis *mechanism* is already reimplemented generically in
[`src/sched/dischg_gate.c`](../../../src/sched/dischg_gate.c) (T15,
[`docs/41`](../../41-charge-discharge-schedule-gates.md)); wiring these specific HRs
into it as the resume (start) / cut-off (stop) thresholds is the remaining step.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Write validation (T17, extends T24/T24b):** the whole-HR write-semantics sweep
  ([`test_wrsem_sweep.py`](../../../tests/test_wrsem_sweep.py) /
  [`wrsem_contract.py`](../../../tests/wrsem_contract.py) /
  [`wrsem_expected.py`](../../../tests/wrsem_expected.py)) pins the factory's dongle
  verdicts — HR 162 `[420,560]`, HR 164 `[15,100]` (out-of-range → exc 3), HR 163/165
  → exc 2 at every boundary — and holds ours' `settings_validate` to the same. Ours'
  side is also checked toolchain-free in
  [`test_settings_validate.c`](../../../tests/test_settings_validate.c) (HR 162/164
  boundary accept/reject; HR 163/165 not-writable exc 2).
