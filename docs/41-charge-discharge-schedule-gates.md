# Charge/discharge schedule gates — the ARM evaluator (T15 hand-off)

> **Research trail.** Where the AC-charge / charge-priority / forced-discharge
> schedules (HR 64-89) and their mode selectors (HR 120) are *evaluated* on the
> ARM, what the verdict is, and why most of this is inert in the image we have.
> Authoritative register surface: [`HR064_089`](wiring/ARM-UART5-dongle/HR064_089-charge-discharge-schedule.md),
> [`HR120`](wiring/ARM-UART5-dongle/HR120-SysEnable.md). Window semantics:
> [`docs/35`](35-focused-microtests.md) / `tests/timewindow_contract.py`.

## TL;DR

A single combined ARM evaluator (`sub_0801ed28`) computes the **discharge-control
"active now" verdict** and writes it to internal RAM bytes `0x2000aa5f/60/61`,
which the main power-control function `sub_0801f438` consumes. Its mode is
**DischgCtrlType** (HR 120 bits 4-5: 0 = by voltage, 1 = by SOC, 2 = both). The
**by-voltage path is a latched hysteresis** on the battery voltage — now fully
cracked and **reproduced byte-for-byte** against the factory oracle:

```
v = (uint16 safety-bank battery voltage @+0x0a) / 10          # signed divide
active = active ? (v >= stop) : (v >= start)                  # start +0x46, stop +0x48
```

i.e. discharge turns **on** once V reaches `start`, stays on until V drops **below**
`stop`, then turns off — a deadband that keeps the verdict from chattering. Our
firmware now has the pure reimplementation `inv_dischg_volt_gate()`
([`src/sched/dischg_gate.c`](../src/sched/dischg_gate.c)), host-tested
([`test_dischg_gate.c`](../tests/test_dischg_gate.c)) and verified against the real
evaluator ([`test_dischg_gate.py`](../tests/test_dischg_gate.py), `make test-sim`).

**Correction of the earlier draft of this doc:** it called `0xaa5f` an "AC-charge
feature-enable that ignores the window". That was wrong — it came from feeding the
*wrong* mode bits (I read the mode as ACChargeType / bits 1-3; the evaluator uses
**bits 4-5 = DischgCtrlType**) and not seeding the voltage path. With the voltage
mode + thresholds + bank voltage seeded, `0xaa5f` is the discharge-by-voltage
hysteresis verdict above.

## The evaluator

| item | value | confidence |
|---|---|---|
| evaluator entry | **`sub_0801ed28`** (flat `com_flat.bin`; right after the AC-First wrapper `0x0801ece8`) | high (disasm + dynamic) |
| verdict bytes | **`0x2000aa5f`, `0x2000aa60`, `0x2000aa61`** (the evaluator `strb`s to all three) | high (disasm) |
| `0xaa5f` | **discharge-by-voltage** verdict (hysteresis, below) | **high (factory-verified, T15)** |
| `0xaa60` | **discharge-by-SOC** verdict (mode 1; reads the battery-limit struct `0x2000a68c`) | medium (disasm; needs T11) |
| `0xaa61` | third discharge sub-verdict / combined | low (inferred) |
| consumer | **`sub_0801f438`** (the main power-control function) holds these in its literal pool and reads them | high (literal-pool xref) |
| master-enable | discharge feature enable = **`settings+0x23` bit 13** (clears the whole block when 0) | high (dynamic) |
| mode selector | **DischgCtrlType** = `settings+0x33` bits 4-5 (HR 120, [`HR120`](wiring/ARM-UART5-dongle/HR120-SysEnable.md)): 0 voltage, 1 SOC, 2 both | high |
| voltage thresholds | **start `settings+0x46`**, **stop `settings+0x48`** (compared to bank V `/10`) | high (factory-verified) |
| mode 2 "both" | ORs the voltage and SOC verdicts, then gates on operating state (`0x40`/`0x80` run states) + status `0x2000a75c` | medium (disasm) |

So the gate is genuinely **"V / SOC with hysteresis"** as T15 anticipated — the
voltage half is closed; the SOC half (mode 1) reads the derived battery-limit
struct and is the T11-dependent remainder.

### How it was verified

Driving `sub_0801ed28` in isolation on `com_flat.bin` (seed the discharge
master-enable `settings+0x23` bit 13, DischgCtrlType = 0 at `settings+0x33` bits
4-5, `start`/`stop` at `settings+0x46`/`+0x48`, battery voltage at safety-bank
`+0x0a`, and the prior verdict at `0x2000aa5f`), then reading the verdict back,
reproduces the hysteresis exactly on both edges and both latch states. With
`start=480, stop=460`: from **off** it turns on only at V ≥ 480; from **on** it
turns off only at V < 460; in the 460–480 band it holds its prior state. Our pure
`inv_dischg_volt_gate()` agrees on every vector ([`dischg_gate_contract.py`](../tests/dischg_gate_contract.py)).
(This also confirms this image's safety bank is at `0x20009e54`, the "ceaa05"
address — cf. the ceaa-07xx bank `0x2000ce5c`, T02a.)

## Why most of T15 is inert in this image

From the live dongle capture (T10,
[`dsppush_contract.py`](../tests/dsppush_contract.py) `INERT_64_89`):

| feature | config regs | writable on `com_flat.bin`? |
|---|---|---|
| AC-charge window | HR 68-73 | **yes** (and pushed to DSP block 4) |
| AC-charge power | HR 66 | yes (stored; not pushed) |
| AC-charge SOC | HR 67 | **no** — inert |
| Charge-priority | HR 74-81 | **no** — inert |
| Forced-discharge | HR 82-89 | **no** — inert |

So on this image the only schedulable, externally-drivable charge/discharge feature
is **AC-charge by time**, whose windows already reach the DSP. The SOC-gated and
charge-priority / forced-discharge paths exist in the evaluator code but cannot be
configured through the dongle here, so they can be neither exercised end-to-end nor
reimplemented against an oracle. (A variant/image that exposes those features — e.g.
the `ceaa-07xx_vE_260214` build the `acchg` micro-test targets, not in the tree —
would let them be driven.)

> **Note — two different things both called "discharge/charge gating".** The table
> above is the **HR 64-89 time-window schedules** (AC-charge/charge-priority/
> forced-discharge), whose *windows* the ARM commits + pushes to the DSP. The
> **DischgCtrlType V/SOC gate** cracked at the top of this doc is a **separate**
> mechanism (HR 120 bits 4-5, thresholds at `settings+0x46/+0x48`) that decides
> whether discharge is allowed by battery voltage/SOC — not a time window. The
> voltage half of that gate is **live and reproduced**; the window schedules remain
> as the table shows.

## State of our firmware

Our firmware covers the ARM's **live** schedule/gate responsibilities on this image:
- **AC-First** window evaluated against the RTC → IR 126 bit 8
  (`src/sched/acfirst.c`, `acfirst_window_active`).
- **AC-charge** windows committed and pushed to the DSP (config block 4,
  `src/dsp/dsp_slots.c` + `dsp_config.c`, T10).
- **Discharge-by-voltage hysteresis gate** — `inv_dischg_volt_gate()`
  (`src/sched/dischg_gate.c`), the pure reimplementation of `sub_0801ed28`'s
  voltage path, host-tested + factory-verified (T15). *Not yet wired into a
  control path* — ours has no discharge-power controller to consume the verdict
  yet (the factory's consumer is `sub_0801f438`); it lands as a verified building
  block, like the slot-committer did ahead of its integration.

It deliberately does **not** implement the inert charge-priority / forced-discharge
/ AC-charge-SOC **window** features (nothing on this image can configure or observe
them). This is a decision to record, not a gap to paper over.

## Hand-offs (what would close the rest of T15)

1. **The discharge-by-SOC path (DischgCtrlType mode 1)** reads the derived
   battery-limit struct `0x2000a68c` — **T11**'s output — so its exact decode (and
   a `0xaa60` oracle like the voltage one) depends on T11. Mode 2 ("both") ORs the
   voltage and SOC verdicts, then gates on operating state + status `0x2000a75c`.
2. **Wire `inv_dischg_volt_gate()` into a control path** once ours has a
   discharge-power/limit controller (the verdict should gate discharge, as the
   factory's `sub_0801f438` does). Also decide the thresholds' holding registers:
   `settings+0x46/+0x48` are the discharge start/stop voltages — map them to their
   HRs (not yet pinned) and feed them from the register model.
3. **The HR 64-89 time-window schedules** (separate from the V/SOC gate): charge-
   priority / forced-discharge / AC-charge-SOC are inert on `com_flat.bin`; a
   variant/image that exposes HR 67 / 74-89 (e.g. `ceaa-07xx_vE_260214`) would let
   them be driven, and the `acchg` time-window oracle (`timewindow_contract.py`
   `EVALUATORS["acchg"]`, evaluator `0x08034590`) run (it currently **skips** on
   `com_flat.bin`).
4. **Verdict consumer (resolved):** `0x2000aa5f/60/61` are **not dead** — they are
   referenced from `sub_0801f438` (the main power-control function; confirmed by a
   literal-pool cross-reference). Tracing exactly what that function does with them
   (discharge power to the DSP block 1? a relay?) is the remaining downstream work,
   which overlaps T10 (block 1) / T11.
