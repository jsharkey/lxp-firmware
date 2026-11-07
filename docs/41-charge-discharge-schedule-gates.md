# Charge/discharge schedule gates — the ARM evaluator (T15 hand-off)

> **Research trail.** Where the AC-charge / charge-priority / forced-discharge
> schedules (HR 64-89) and their mode selectors (HR 120) are *evaluated* on the
> ARM, what the verdict is, and why most of this is inert in the image we have.
> Authoritative register surface: [`HR064_089`](wiring/ARM-UART5-dongle/HR064_089-charge-discharge-schedule.md),
> [`HR120`](wiring/ARM-UART5-dongle/HR120-SysEnable.md). Window semantics:
> [`docs/35`](35-focused-microtests.md) / `tests/timewindow_contract.py`.

## TL;DR

The three parallel charge/discharge schedule features each produce an **"active
now" verdict** computed ARM-side by a single combined evaluator, landing in three
consecutive ARM RAM bytes. But in the image we test against (`com_flat.bin`), the
**config registers for two of the three features are inert** (not dongle-writable,
T10), and the AC-charge verdict in isolation tracks the **feature-enable**, not the
time window — the ARM pushes the AC-charge *windows* to the DSP and the DSP does the
time-gating. So for **our** firmware there is little to add on this image beyond
what already exists (AC-First window → IR 126 bit 8; AC-charge windows → DSP block
4). The remaining decode is a hand-off, below.

## The evaluator

| item | value | confidence |
|---|---|---|
| evaluator entry | **`sub_0801ed28`** (flat `com_flat.bin`; sits right after the AC-First wrapper `0x0801ece8`) | high (disasm + dynamic) |
| verdict bytes | **`0x2000aa5f`, `0x2000aa60`, `0x2000aa61`** (three consecutive bytes the evaluator `strb`s to) | high (disasm) |
| feature → byte | AC-charge → `0xaa5f`; charge-priority → `0xaa60`; forced-discharge → `0xaa61` | `0xaa5f` confirmed; `0xaa60/61` **inferred by position** (register-group order) |
| per-feature master-enable | a bit in `settings+0x23` (AC-charge = **bit 13**: setting it drives `0xaa5f`→1) | `0xaa5f`/bit 13 confirmed dynamically |
| mode selector | `settings+0x33` = **HR 120 stSysEnable** (ACChargeType bits 1-3, DischgCtrlType bits 4-5, … — [`HR120`](wiring/ARM-UART5-dongle/HR120-SysEnable.md)) | high (matches HR120 doc + the `acchg` evaluator gate) |
| other inputs read | `settings+0x46`, battery-limit struct `0x2000a68c`/`0x2000a6a0`, status `0x2000a75c` (bits 11/15) | medium (disasm; roles not all pinned) |

So the gate is genuinely **"window × SOC × V"** as T15 anticipated: a master-enable,
then a mode (time / voltage / SOC, per HR 120), then the matching threshold/window
and live SOC/limit/status inputs.

### What was pinned dynamically

Driving `sub_0801ed28` in isolation (seed `settings`, RTC `0x2000a718`, read the
verdict bytes):
- With the AC-charge master-enable (`settings+0x23` bit 13) **set**, `0x2000aa5f`
  reads **1 regardless of the time of day or the window** (even an empty window).
  So `0xaa5f` in isolation reflects **"AC-charge feature enabled"**, not
  "window active now".
- `0x2000aa60`/`0x2000aa61` stayed 0 in every seeding (their master-enables were
  not set) — consistent with the charge-priority / forced-discharge features being
  inert here (below).

This fits the division of labour already established for AC-charge: the **ARM
pushes the AC-charge window times to the DSP** (config block 4, T10 /
[`field-provenance`](wiring/ARM-USART3-DSP/field-provenance.md)) and the **DSP**
time-gates them in its FSM (the `g_outputPrio==2 && flags` idiom,
[`block-00`](wiring/ARM-USART3-DSP/block-00-output-priority.md)). Contrast AC-First,
where the ARM *does* evaluate the window itself and surfaces the verdict at IR 126
bit 8 (docs/25).

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

## State of our firmware

Our firmware already covers the ARM's **live** schedule responsibilities on this
image:
- **AC-First** window evaluated against the RTC → IR 126 bit 8
  (`src/sched/acfirst.c`, `acfirst_window_active`).
- **AC-charge** windows committed and pushed to the DSP (config block 4,
  `src/dsp/dsp_slots.c` + `dsp_config.c`, T10).

It deliberately does **not** implement the inert charge-priority / forced-discharge
/ AC-charge-SOC gates (nothing on this image can configure or observe them), nor the
internal `0x2000aa5f/60/61` verdicts (ARM-internal; AC-charge is DSP-gated). This is
a decision to record, not a gap to paper over.

## Hand-offs (what would close the rest of T15)

1. **Reconcile the evaluator's inputs: settings vs committed slot records.** Seeding
   raw `settings+0x3a` windows did not move the verdict; the evaluator likely reads
   the **committed slot records** (`0x2000a330…`, the slot-committer family) the way
   the config builder does, not the raw settings struct. Pin which, then the
   time/SOC gate can be driven in isolation.
2. **A variant/image that exposes HR 67 / 74-89** (e.g. `ceaa-07xx_vE_260214`): the
   `acchg` time-window oracle (`timewindow_contract.py` `EVALUATORS["acchg"]`,
   evaluator `0x08034590`) is written for it and currently **skips** on `com_flat.bin`
   — see that file and [`docs/39`](39-parity-roadmap.md) T15.
3. **Battery-limit inputs** (`0x2000a68c`): the SOC/voltage gate reads the
   derived battery-limit struct, which is **T11**'s output. The SOC-gate decode
   depends on it.
4. **Trace the verdicts downstream:** where `0x2000aa5f/60/61` are consumed
   (relays? a status IR? the DSP push?) — not yet established.
