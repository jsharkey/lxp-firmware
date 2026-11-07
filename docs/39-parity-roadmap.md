# Parity roadmap — the task list toward factory-behaviour parity

This is the **work queue** for getting the open firmware to **behavioural parity
with the factory `ceaa-07xx` image**. It is written for several agents working
**in parallel**. Each task is sized to be one agent's job (most are a few
commits). Tasks are **ordered by impact**: the ones near the top either close the
biggest gaps or unblock the most later tasks.

Companion: [`docs/38-oss-feature-ideas.md`](38-oss-feature-ideas.md) covers OSS features *beyond* the factory; this doc is about reaching parity first.

It is a plan, not a finding. Every claim below about what exists today cites the
file or doc it comes from (as of `ccccc95`). Where a task says what the factory
*does*, that is only as strong as the doc it cites. **Re-prove it with an oracle
test before you build on it.**

**Scope.** We want functional parity on every external interface: dongle
Modbus, the CAN BMS, the DSP / safety-CPU links, relays, and persistence. The
HMI is the exception. **We do not reimplement the factory's settings editors.**
A read-only **overview / status dashboard** on the real panel is enough
(task T13). Settings stay editable over Modbus.

---

## How to work a task (the TDD loop, made explicit)

Every task follows the same two-step shape. This is the oracle discipline from
[`docs/19`](19-gpio-test-harness.md) §"Adding a behaviour" and
[`docs/35`](35-focused-microtests.md):

1. **Oracle first.** Write the test against the **factory image** and make it
   **green there**. That test *is* the spec. Pick the cheapest layer that can
   express the behaviour:
   - **Micro-test** ([`docs/35`](35-focused-microtests.md) pattern, e.g.
     `tests/timewindow_contract.py`): call **one factory function in isolation**
     under Unicorn, with only its inputs seeded, and run **one vector table**
     against both the factory function and our function (which our side calls by
     ELF symbol). Use this for **nuanced, boundary-heavy logic**: window edges,
     hysteresis thresholds, timeout expiry, scaling/rounding, clamps,
     bit-packing, classifier tables. These tests are fast and exhaustive, so
     sweep the boundaries: `t-1`, `t`, `t+1`, midnight wrap, 0 / max / overflow.
   - **Simulator test** (`make test-sim`, `tests/test_arm_sim*.py`): boot the
     whole image and drive it as a **black box** over its real interfaces
     (dongle Modbus, CAN mailbox, GPIO, SPI flash, the peer banks). Use this for
     **end-to-end paths**: "a CAN frame arrives → the dongle reads it back",
     "write HR → reboot → reads back", "mode changes → relay moves". Keep the
     number of e2e tests small. Each one should cover a whole path, not a single
     boundary.
   - Put the vectors/contract in a shared `*_contract.py`, and put both backends
     behind it, so **one test body judges both firmwares** and a third assertion
     checks that they **agree**.
2. **Then ours.** Implement in `src/` and make the **same test green for ours**.
   If the logic is narrow, factor it as a **pure function** (registers + clock
   in, verdict out, no globals). That makes it callable from a host test
   (`make test`), from the Unicorn micro-test, and from `main.c`.

House rules that apply to every task (all from [`AGENTS.md`](../AGENTS.md)):

- A sim test **may land red for ours** if it is **green for the factory**. Mark
  it a known-red-for-ours spec in the test and in the commit. `make test` and
  the builds must **stay green**.
- Record every register you test in its
  [`docs/wiring/ARM-UART5-dongle/`](wiring/ARM-UART5-dongle/registers.md) `## Test coverage` section.
- Anything the factory does that looks wrong goes in
  [`docs/31`](31-factory-quirks.md), with a verdict. **Don't silently copy or
  "fix" it.**
- New wire/register facts belong in the authoritative subdirs
  (`docs/wiring/`, `docs/wiring/ARM-UART5-dongle/`, `docs/wiring/ARM-USART3-DSP/`), not only in a
  numbered doc.
- If you can't run the factory half (no image), say so in the commit. Never
  claim a pass you didn't see.

### Claiming a task (collision avoidance)

**Status emoji** — prefix each `**Status:**` line so a human can scan the board at
a glance, kept in sync with the `[ ]`/`[~]`/`[x]` marker (which tooling still
parses): ⬜ open · 🚧 claimed / in-progress (or partially done) · ✅ done.

To claim a task, edit its **Status** line to
`[~] <agent/handle> <YYYY-MM-DD>` (emoji 🚧), commit it on its own
(`docs/39: claim T07`), and push **before** you start the real work. If the
rebase shows someone else claimed it first, pick another task.

When you finish, set the line to `[x]` (emoji ✅), link the commits/docs/tests, and tick
the matching README Status box if there is one. Then **move the task's whole
section** (its `### Txx` heading down to the next task heading, sub-tasks
included) **to the end of the [Completed tasks](#completed-tasks) section**, in
the same commit. That way the P0-P3 sections above hold only open or
in-progress work. Keep its heading text and ID unchanged, because other docs
link to it. A task that is only partly done (some sub-tasks still `[ ]`) stays
where it is until every part is `[x]`.

If a task turns out bigger than its card, split it: add `T07a`, `T07b` under it
rather than renumbering. Other agents reference these IDs.

Several tasks touch `src/main.c`, so keep your edits there small. Each task
should land its logic in its **own module** (`src/<area>/…`) and add only a
call/wiring line or two to `main.c`. Rebase often.

---

## Where we stand (gap snapshot)

| area | factory | ours today | gap |
|---|---|---|---|
| Dongle Modbus port | UART5 + RS-485 DE ([`wiring/ARM-UART5-dongle`](wiring/ARM-UART5-dongle/README.md)) | **UART5 + DE on PA15** (`src/uart/uart5.c`); USART3 left to the DSP (`src/dsp/dsp_link_port.c`) | **closed (T01)**; harness auto-detects UART5 (ours) / USART3 (factory, its UART5 RX is a T02 task) |
| Settings persistence | 56 HRs pinned in slots 0/5 ([`docs/23`](23-arm-config-writer.md)) | **62** persisted via `include/inv/settings_map.h` (T03): docs/23's 56 + 6 AC-First windows, cross-image green | gated schedules (74, 76-89), Q(V)/PF block — need a precondition |
| Write validation | factory getters/setters range-check (unverified) | `/* TODO: validate ranges */` in `mb_wr_hold` | unknown, needs oracle |
| Safety-CPU USART2 | wire frame → bank → IR ([`docs/33`](33-usart2-telemetry-bank.md)) | bank → IR only (`src/safety/safety_cpu.c`). **No USART2 driver or parser**; tests poke `g_safety_bank` | RX parser, IR 0 / 6 / 60-63 not published |
| State / fault classifier | `sub_0801a678` ([`docs/22`](22-arm-dsp-core-split.md)) | **`inv_classify()`** publishes IR 0 + IR 60-63 (`src/state/classify.c`); **pure pass-through pinned on the 07 oracle (T06b)** — IR 0 = mode byte verbatim, fault/warn compose to IR 60-63; fed live from USART2 (T05) | — (closed) |
| ARM-computed telemetry | powers, RunningTime, etc. ([`docs/22`](22-arm-dsp-core-split.md), [`ARM-UART5-dongle`](wiring/ARM-UART5-dongle/registers.md)) | **serve layer done** (`src/telemetry/`, T07: powers /10, Seps 1:1, RunningTime split) + energy integrator (`src/energy/`); internal values injected until the DSP/safety compute lands | the upstream V·I / sign-split **compute** (source is the **USART2** safety-CPU bank, T05 — *not* a USART3 `0x49`; corrected by T09). IR 19 PF + IR 107 now served from the bank (T07b); IR 77/64/67 are **not** bank-relayed (corrected T07b) |
| DSP link RX (USART3) | **Modbus-slave + bootloader demux** (`sub_0801c3e6`); NOT a `0x49` parser — that's USART2 ([`wiring/ARM-USART3-DSP/telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md)) | **demux + Modbus-serve done** (`src/dsp/dsp_rx.c` + `dsp_rx_port.c`, T09) | **closed (T09)**; link-loss supervision is T08 |
| DSP config push | 9 blocks fully populated | block 0 partial, blocks 4/5 (slots) done, **1-3, 6-8 empty** (`src/dsp/dsp_config.c`) | 6 block payloads |
| BMS / CAN | RX decode, limit derivation, keep-alive, `0x35A` | RX decode for 0x351/355/356/359 (`src/can/bms_can.c`). Keep-alive payload is "provisional" | limits → DSP, TX payload, quirks Q1-Q4 |
| Command registers | HR 11 reset / defaults / reboot, HR 15 addr, SN | **HR 11 one-shot dispatch** (`src/state/command.c`: energy-clear, BMS switch, real reboot; defaults/adj/fault/monitor accepted-ignored), **HR 15 live address change** (after reply, loaded on boot), HR 9 own-version read-back, **HR 10 low live DSP version** + **W008 identity compare** (vs "ceaa", latched; `src/safety/safety_cpu.c`); `check_sn=false` (T12, W008/HR10 pinned by T02b) | defaults/adj/fault/monitor record ops; health-bit→WarningCode gating for W008 (T06b); wrong-SN factory behaviour (factory-dongle UART5 harness) |
| Schedules | AC-First + AC-charge windows evaluated ARM-side | AC-First window verdict only (`src/sched/acfirst.c`); optchg is dormant in the factory too (Q5) | charge/discharge/gen schedules + SOC/V gates |
| Relays | driven by the mode task `sub_0801b3dc` ([`docs/18`](18-power-path-relays.md)) | `src/relay.c` mirrors 2 contracts | sequencing under the live mode |
| HMI | full menu + editors | menu engine on the real panel (`src/hmi/`) | **status dashboard** (editors out of scope) |
| Harness depth | — | factory RTOS tasks **don't run** in the sim, so peer data is injected at the bank, not on the wire ([`docs/19`](19-gpio-test-harness.md), `tests/arm_sim_safety.py`) | wire-level e2e for USART2/USART3/relay task |

Register-level coverage is now tool-tracked (T22): **`make coverage-report`**
([`tools/reg_coverage.py`](../tools/reg_coverage.py)) cross-references the register
map, the tests and each register's `## Test coverage` doc section. As of the T22
catch-up, **10 of 54** `docs/wiring/ARM-UART5-dongle/` register files still name no
test (was a hand-counted ~22); the tool also lists the registers no test touches at
all (section B) and fails (`--check`, run by `make test`) if a test covers a
register its doc doesn't record. Run the tool for the live figure rather than
trusting a number frozen here.

---

## P0 — unblockers and the biggest gaps

_T01-T04 are done; see [Completed tasks](#completed-tasks). T22 was added on
2026-11-07 from a coverage audit of the dongle register docs._

### T22 — Register-coverage bookkeeping: catch up, then automate it
**Status:** ✅ `[x] claude/019chjb 2026-11-07` ([`tools/reg_coverage.py`](../tools/reg_coverage.py), `make coverage-report`/`coverage-check`) · **Layer:** docs + a read-only tool · **Independent** · **Unblocks:** honest gap counts for T23-T27

An audit on 2026-11-07 found the per-register `## Test coverage` sections in
[`ARM-UART5-dongle/`](wiring/ARM-UART5-dongle/registers.md) **lagged the tests that
already exist**, so the gap list overstated what was untested. **Done:**
- **Catch-up.** Recorded the T03 cross-image persistence (`SETTINGS_MAP` /
  [`settings_persist_contract.py`](../tests/settings_persist_contract.py), proven by
  `test_persist_crossimage.py`) in the 11 HR docs that omitted it — `HR015`, `HR020`,
  `HR023_024` (HR 23), `HR025_062` (grid-protection subset), `HR064_089` (64-66,
  68-73, 75), `HR103`, `HR105`, `HR110`, `HR112`, `HR120`, `HR147_148` (HR 147) — and
  the Epv1 energy coverage (IR 28/40/41) in `IR028_059`. The "N of 54 files list no
  test" figure dropped from a hand-counted ~22 to **10** (`make coverage-report`).
- **Automated.** [`tools/reg_coverage.py`](../tools/reg_coverage.py) (read-only;
  no image needed) cross-references `modbus_map.h`, the shared contract tables
  (`SETTINGS_MAP`, `WRITE_VECTORS`, `SAFETY_TELEMETRY`, the telemetry/energy/DSP-push
  contracts) and an `IR_*`/`HR_*` + numeric-read/write scan of `tests/`, against each
  register's `## Test coverage` section. It prints **(A)** docs that under-record a
  covering test (the catch-up list — now 0), **(B)** registers no test touches at
  all, and `--matrix` for the full register × test grid.
- **Wired up.** `make coverage-report` (full report), `make coverage-check` (quiet
  pass/fail), and **`make test` runs `--check`** so a new test that isn't recorded in
  its register's doc fails fast. The frozen gap figures in this doc now point at the
  tool instead of a hand count.

---

## P1 — the live data path (telemetry, state, faults)

### T08 — Peer-link supervision: comms-loss faults, timeouts, recovery
**Status:** `[x]` — all three peer legs wired + tested (safety/E017, BMS/W000, DSP/E000), 2026-11-07 · claude · **Layer:** sim + micro · **Depends:** T05/T09 wires (done), T06 (done)

What happens when the DSP, safety CPU or BMS goes quiet? Each peer leg raises its
comms-loss code and recovers on the next good frame/poll:

- **Safety link → E017 (done).** Peer-comms-loss on USART2 sets **E017** (FaultCode
  bit 17, `0x20000`) — the ARM-local peer-comms-loss bit the factory also uses
  (docs/29/30; the factory tracks it in its USART2 frame-health counter
  `0x2000a6c4` / `0x20009048+6`). Ours: once a CRC-valid frame has been seen, the
  loop raises E017 when `safety_rx_link_ok(now, SAFETY_LINK_TIMEOUT_MS)` goes false
  and clears it on the next good frame (`src/main.c`, hooks from `safety_rx_port.c`,
  T05). Tested e2e on the real USART2 wire: `test_safety_link_loss_raises_e017`
  (`tests/test_arm_sim_self_only.py`) — alive → E017 clear, quiet past the timeout →
  E017 set, fresh frame → clears.
  - **Factory threshold is sim-blocked (not T02).** The exact timeout is *not*
    observable in the bare harness: feeding the USART2 wire then going silent for
    155M instructions never moves the factory's comms-loss counter
    (`0x2000a6c4`/`0x20009048+6`) nor sets E017, because that frame-health bookkeeping
    is an **unscheduled periodic task** (the USART2 driver `sub_080259d8`), the same
    class of harness limit as the dongle-UART5 task. So `SAFETY_LINK_TIMEOUT_MS` is a
    conservative default (1 s) pending a bench capture; the *mechanism* (which bit,
    which direction, recovery) is pinned statically (docs/29/30) and proven on ours.
- **BMS link → W000 (done).** BMS/CAN comms-loss sets **W000** (WarningCode bit 0,
  "Battery communication failure" — spec Table 10). Ours: `on_can_frame` stamps the
  last recognised-pack-frame tick; once a frame has been seen, the loop raises W000
  when none arrives within `BMS_LINK_TIMEOUT_MS` (5 s, conservative) and clears it on
  the next good frame (`src/main.c`; `inv_classify` composes `INV_LOCAL_WARN_W000`).
  Tested e2e on CAN1: `test_bms_link_loss_raises_w000` (`tests/test_arm_sim_self_only.py`)
  — alive → clear, quiet past the timeout → set, fresh pack frame → clears. Host:
  `test_classify.c` W000 composition. (Factory threshold sim-blocked, as for E017.)
- **DSP (USART3) link → E000 (done, RE-confirmed).** **E000** ("Internal
  communication fault 1") is now confirmed by static RE (not just elimination) to be
  the **DSP/USART3** internal-comm fault — see [`docs/30`](30-safety-cpu-arm-handoff.md)
  "E000 = DSP link (07 RE)". In the 07 image (`com_flat.bin`) the ARM-local fault
  accumulator is `0x2000d808` (07 twin of 05's `0x2000a6c4`; the classifier
  `sub_0801a678` keeps bits 0 and 17 of it), and **E000 (bit 0) is set inside the DSP
  config-push builder `sub_080273b4`** (at `0x080276f8`, `[0x2000d808] |= 1`), gated on
  DSP-link health (health words `0x2000d9c8` bit 10 / `0x2000d890` bit 13); the
  DSP-RX reset handler `sub_080359b8` arms a ~300-unit timeout and sets the health
  bits. Ours: the DSP polls us as a Modbus master on USART3, so a served poll is the
  liveness signal; once one has been seen, the loop raises E000 when
  `dsp_rx_link_ok(now, DSP_LINK_TIMEOUT_MS)` goes false and clears it on the next poll
  (`src/main.c`; hooks added to `dsp_rx_port.c`). Tested e2e: `test_dsp_link_loss_raises_e000`
  (`tests/test_arm_sim_self_only.py`) — alive → clear, quiet past the timeout → set,
  next poll → clears. (Factory threshold sim-blocked, as for E017/W000.)

### T10 — Fill the DSP config-push payloads (blocks 1, 2, 3, 6, 7, 8 + rest of 0)
**Status:** 🚧 `[~] claude 2026-11-07 · claude-opus/019chjbE 2026-11-07 (blocks 3/6 scalars + block-0 enable core + generator charge)` — blocks **1/2/7/8** byte-identical; **every HR-driven field in blocks 0, 3, 4, 5, 6 now emitted byte-faithful ours==factory** (grid-charge + generator-charge scalars, schedule windows, and block-0 packed enable/priority core). What remains is the **non-HR constant templates** (block 0 identity/version, block 4/5 `0x23+` tails) — now **decoded** as boot-computed **settings/model defaults** (not a flash const, not per-unit config), so byte-exact parity there is a settings-defaults (T03) + model-constant task, not a push-mechanism gap · **Layer:** sim (byte-exact frame diff) · **Independent** (per-block)

Block meanings are recovered ([`wiring/ARM-USART3-DSP/`](wiring/ARM-USART3-DSP/fields.md):
1 = battery limits, 2/7/8 = calibration gains, 3/6 = grid-charge slots), but
`dsp_config.c` sends 0/3/4(partial)/5(partial)/6 **empty**. `tests/test_dsp_push.py`
captures the factory's frames off USART3.

**The oracle was broken — now fixed (the real blocker, a 05→07 address drift).**
`dsppush_contract.py` called the factory per-block filler at `sub_08024dfc`, a 05-era
"conversion" of docs/10's `FUN_08026830`. In this 07 flat image (`0x08000000` base)
that address is **mid-function** and writes nothing → the live factory capture
returned all-zeros, so blocks 2/7/8 were only ever checked against the derived spec,
not a live capture. Fixed: the real filler is **`0x08026830`** read at the flat base
(builder `0x080273b4`), and the call must **quiesce the RTOS engine** first (the
factory's live SysTick/PendSV would `emu_stop` the single-shot `sim.call`). With
that, the filler reproduces every block from the real 07 working RAM — blocks 2/7/8
come out unity `0x0400` byte-for-byte (`test_dsp_push.py` now **6/6 green**, was 1/6).
[`field-provenance` §The real builder](wiring/ARM-USART3-DSP/field-provenance.md).

**Verified per-block (ours vs the now-working factory oracle):**
- **Blocks 2, 7, 8** (calibration gains): **MATCH** — constant Q10 unity `0x0400`
  (no holding register feeds them). `src/dsp/dsp_config.c`.
- **Block 1** (battery limits): **MATCH** at the no-BMS boot state (both empty);
  the populated case is the T11 limit derivation.
- **Block 3** (grid-charge slot): **HR 105 EOD → `0x1b`**, **HR 103 feed-in limit →
  `0x1c`** (both u8 %). Ours==factory. The rest of the block is a constant template.
- **Block 6** (grid-charge slot): lead-acid **HR 101/102** currents (→ `0x17`/`0x1b`,
  ×10), **HR 99** charge-volt (→ `0x25`), and the **generator-charge** set
  **HR 194–198** (→ `0x1d`/`0x1f`/`0x21`/`0x22`/`0x23`). Ours==factory. Only the
  `0x19` word (const) is undecoded.
- **Block 4** (AC-charge): window times `0x17..0x22` MATCH; tail `0x23+` is a
  constant template (below).
- **Block 5** (AC-First): window times `0x17..0x22` MATCH; tail `0x23+` constant.
- **Block 0**: the HR-driven **enable/priority core now emitted byte-exact**
  (`dsp_build_block0`): HR 120 `SYS_ENABLE&0xFE → 0x19`, HR 90/91 EPS volt/freq
  (packed) → `0x1a`, HR 110/112 `FUNCTION_EN1`/`SET_SYSTEM_TYPE` (packed) → `0x1c`,
  HR 145 priority → `0x1e`, HR 20 `PV_INPUT_MODEL → 0x28`, HR 21 `FUNC_EN` remap →
  `0x2c`. Routing ours==factory (`GRID_PUSH`), encodings locked
  ([`test_dsp_config.c`](../tests/test_dsp_config.c)). The identity/version template
  (`0x15–0x18`, `0x1b`, `0x1d`, `0x1f–0x27`, `0x29–0x2e`) is still a constant to decode.

All five block-3/6 scalars are pinned **differentially** and re-validated with
**single-write fresh captures** (`tests/test_dsp_push.py::test_{factory,ours}_grid_push_matches_spec`,
`GRID_PUSH`; [`block-03_06`](wiring/ARM-USART3-DSP/block-03_06-gridcharge-slots.md)).

**Methodology correction — beware the differential double-write.** `push_delta`
writes A, builds, writes B, builds. A byte that only changes because the *second*
write follows the first (modbus-transaction residue) is a **false positive**. The
earlier "**HR 75 charge-priority SOC → block 4 `0x26` (verified)**" was exactly
that: single-write fresh captures show `0x26` stays `0` for every value 20..90, so
**HR 75 is stored-only (not pushed), like HR 66.** The shared residue also shows up
at payload `0x15/0x16` and block 0 `0x25/0x26` for nearly every register — always
excluded. Every real field above was confirmed by single-write capture.

**Remaining — decoded: the leftover bytes are settings/model defaults, not a push gap.**
The bytes no HR moves (block 4/5 `0x23+` tails, block 0 identity/version template,
and the slot voltage/time defaults in blocks 3/6) were traced (data-flow through the
filler + boot-write hook): they are **boot-computed into the ARM settings/slot
working structs** (`0x2000c8xx`/`0x2000d3xx`; zero pre-boot), **not** a flash const
table (an apparent `0x0802exxx` source was a CRC-table false match) and **not**
external per-unit config. Their values are recognisable **defaults** — `0x2ee0` =
12000 = **12 kW rated** (model-specific), voltage limits `0x01b8`/`0x01a4` = 440/420,
and at HR-driven offsets simply those settings' defaults (block 6 `0x023e` = 57.4 V =
HR 99 default, etc.). So matching them byte-exact is our firmware **adopting the same
settings defaults** (a T03 settings-layer task + the model rated-power constant), not
the DSP-push mechanism — which is complete for every identifiable field. We do **not**
hardcode this model-specific default blob into the push builder.
[`block-03_06 §Constant-template bytes`](wiring/ARM-USART3-DSP/block-03_06-gridcharge-slots.md).
- **Block 3 @0x19** (HR 112 `SET_SYSTEM_TYPE` second target) — mapped, not yet emitted.
- **Block 1 populated** — battery limits from the working struct (depends on T11).
- **Header parity** — payload region exact; the frame header is still ours'
  SN+timestamp vs the factory's `0x41`/len/status (`0x080273b4`). Separate
  [`frame-header`](wiring/ARM-USART3-DSP/frame-header.md) follow-up.
- **Done when:** every block's payload is byte-identical to the factory's for the
  same settings + BMS state.

### T23 — Whole-surface read sweep: every register, both images, one diff
**Status:** 🟡 `[~] claude/019chjb 2026-11-07` · **Layer:** sim (common) · **Independent** · **Highest-leverage coverage task**

Most registers are tested one at a time, on the path some feature happened to
need. Nothing yet checks the **whole map**. Add one common sim test (warm once,
clone per case) that boots both images into the **same seeded state**:
settings written via T03's table, bank and CAN snapshots from the existing
contracts, and a fixed RTC. It then reads **every IR 0-159, IR 5000-5126 and
HR 0-255** in spec-legal chunks (≤40 registers, no 40-group crossing) and
diffs value **or exception code** per register.
- It also asserts the framing rules on both images: a read crossing a 40-group
  boundary, a read longer than 40, a zero-length read, and an out-of-map
  address (which exception, or silence?).
- **Output:** a committed expected-diff table. Every register is one of
  `match`, `known-diff → docs/31 Qn` or `ours-red (task Txx)`. That table *is*
  the parity scoreboard: new work turns `ours-red` into `match`. Reserved
  registers and spec-only (`idx`) registers get covered for free: they read
  back *something*, and now we pin what.
- Run a second pass with a different seeded snapshot. A register that doesn't
  change between passes is either constant or not wired, and the doc should
  say which.

### T24 — Write-semantics sweep across the whole HR surface (extends T04)
**Status:** ⬜ `[ ]` · **Layer:** sim (table-driven) + micro where a setter is isolatable · **Independent**

T04 built the mechanism but its `WRITE_VECTORS` cover only **six** registers
(HR 9, 15, 20, 66, 101, 105). Generate vectors for **every** writable HR in the
spec: `min-1 / min / max / max+1` from the ranges in `modbus_map.h` and the
per-register docs, plus reserved addresses and `0x10` on non-SN/time
registers. Record the factory verdict per register (accept / clamp / exception
code / store-but-ignore). Q6 (one-sided range checks), Q7 (HR 22 not writable)
and Q9 (HR 112 rejects 2) were each found by hand, so this sweep will surface
the rest. Every deviation from the spec goes into docs/31, and every register
file gets a coverage line.
- Include the one identity gap left after T12: a dedicated **SN (HR 2-6)
  `0x10` write → read-back → cold boot** test, which
  [`HR002_006`](wiring/ARM-UART5-dongle/HR002_006-SN.md) still lists as
  uncovered.

### T25 — HR write → DSP push matrix (the side-effect half of every setting)
**Status:** 🚧 `[~] claude 2026-11-07 · claude-opus/019chjbE 2026-11-07` · **Layer:** sim (USART3 capture diff) · **Pairs with:** T10

For most settings HRs, only *storage* is tested (T03). Whether a dongle write
actually **reaches the DSP** is not. **Now mapped live:**
[`tools/dsp_push_matrix.py`](../tools/dsp_push_matrix.py) sweeps every writable HR
(two distinct values, **separate fresh boots** so the modbus-residue false positive
that the `push_delta` double-write produces cannot occur) and records which
block·offset each moves, or `none (ARM-local only)`. Output committed:
[`hr-push-matrix.md`](wiring/ARM-USART3-DSP/hr-push-matrix.md).

**Found (factory):** 29 of 59 push to a block. New vs. the old static table —
block 6 carries the **generator-charge** set (HR 194–198) and lead-acid
charge/discharge (HR 99/101/102); block 0 carries **packed enable bytes** (HR 20,
21, 90/91 shared, 110/112 shared, 120); HR 112 is multi-target (block 0 + block 3).
This supersedes `hr-controlled-fields`' old "live capture impossible" note (that was
a **broken-oracle** symptom — the 05-era filler address — not a real limitation).

**Done:** the factory matrix + the T10-relevant fields (blocks 3 & 6 scalars +
generator-charge) decoded and locked ours==factory in `test_dsp_push.py`
(`GRID_PUSH`). **Remaining:** decode the packed block-0 enable bytes
(`0x19/0x1a/0x1c`) and emit them in ours; a full ours-side matrix sweep; and the
`1-value` registers (145/146/100/113/16/23/61 — only one value stores in the
default boot) need a storing value pair or static confirmation.
- Registers whose effect is evaluated ARM-side (windows aside, which *do* push)
  show `none` here — their behaviour test lives in T15/T16.
- The full sweep (~4 min, needs the proprietary image) is a tool, not a CI test;
  the decoded subset is locked by the fast `test_dsp_push.py` cases.

---

## P2 — features and commands

### T13 — HMI status dashboard (overview screen; no editors)
**Status:** ⬜ `[ ]` · **Layer:** sim (panel framebuffer) + host (layout) · **Soft-depends:** T06/T07 for real values (works with injected values earlier)

Replace the menu-first screen with a read-only **overview dashboard** on the
240×160 panel: PV (V/P per string), battery (V/SOC/charge-discharge P), grid
(V/f/import-export P), load/EPS P, the **operating state**, active
**fault/warning codes**, today's energy, and the clock. Keys page between a few
dashboard pages (summary / battery detail / faults / versions). The existing
menu stays reachable but is not the focus.
- **Oracle:** `make factory-hmi` renders the factory **overview** with its real
  layout ([`docs/28`](28-factory-hmi.md) §Limits: value fields are empty because
  no telemetry is fed). Feed the bank + CAN snapshots from the existing
  fakes/contracts so that the factory overview shows numbers. Then (a) take
  reference screenshots, and (b) record **which value appears for which
  register and with what formatting** (decimals, units, sign, overflow
  display). We match **content and formatting rules**, not pixels. Our layout
  is our own.
- **Ours:** `src/hmi/dashboard.c`. Fields get repainted incrementally (one row
  or field per pass, as now) so comms never stall. A sim test injects a
  snapshot and asserts the decoded text cells on our panel. Run the same
  snapshot through the factory for the formatting oracle.
- Keep the existing incremental-repaint budget: the "comms boot budget"
  comment in `main.c` is a real constraint.

### T14 — Relays under the live mode: transfer sequencing, gen / AC-couple, dry contact
**Status:** 🚧 `[~] claude 2026-11-07` — **AC-transfer (PA12/PB3) state→relay map cracked + reimplemented + factory-verified** (T14a enable prerequisite solved); gen/AC-couple (PC5), dry-contact (PD11), enable *provenance* + sequencing *timing* remain · **Layer:** sim · **Depends:** T02 (relay task runs), T06 (real state)

**Done (AC-transfer pair, 2026-11-07).** Cracked the T14a prerequisite the prior
attempt was stuck on: the AC-transfer enable is **`0x2000d9ca` bit 3 OR `0x2000d810`
bit 4**, and — the key insight — the *state→relay* oracle does **not** need the
enable-deriver (`sub_0801887c`). The prior attempt ran the full RTOS loop, where the
deriver re-clears the enable each pass; driving the relay function `sub_08018a7c`
**in isolation** with the enable set directly reaches the grid-eval path and the pair
switches by grid state. Verified byte-for-byte on `ceaa-07xx` (clocking past the three
50-tick debounces, reading the relay setters `sub_08033536`=PB3 / `sub_080334fc`=PA12):

| enable | DSP grid (`0x2000ce5c+0xbc`) | PA12 | PB3 |
|---|---|---|---|
| off | any | 0 | 0 |
| on | qualified (bit 20 set & bits 29-30 ≠ 2) | 0 | 1 |
| on | not qualified | 1 | 1 |

Reimplemented as pure [`inv_ac_transfer_decide()`](../src/relay.c) (host test
[`test_ac_transfer.c`](../tests/test_ac_transfer.c)) + factory oracle
([`test_ac_transfer.py`](../tests/test_ac_transfer.py), `make test-sim`). Full decode
in [`docs/18`](18-power-path-relays.md).

**Sequencing timing — DONE (2026-11-07).** The transfer PA12 switches behind a
**symmetric 50-tick debounce** (`0x2000dba4/5/6`): once enabled+settled, flipping the
grid qualification takes exactly 50 `sub_08018a7c` calls either way. Locked by
[`test_ac_transfer.py`](../tests/test_ac_transfer.py)`::test_factory_transfer_debounce_is_50`.

**Remaining (narrowed this pass):**
- **Enable provenance (still elusive):** clocking `sub_0801887c` 800× sets `d9ca`
  **bit 1** from config `0x2000d0e4+4` bit 9 (and `d810` bit 3), but **never** the
  AC-transfer enable `d9ca` bit 3 / `d810` bit 4 for any config+grid input; the 3
  other `d9ca` writers (`sub_080147ac` init-zero, `sub_080358dc` bit 7,
  `sub_0801ef48` getter) don't set it either. So the enable comes from an
  unidentified condition — **possibly inert on this image** (cf. T15), leaving the
  manual-override path (already mirrored) operative. Pinning it is what wires
  `inv_ac_transfer_decide()` live. (docs/18.)
- **PC5 (gen/AC-couple, `sub_08017022`)** and **PD11 (dry-contact, `sub_08035ef2`)**
  are **not** clean state→relay maps (executed decode, docs/18): PD11 only ever
  *closes* (grid/EPS `+0xc4` bit1 latch → GPIOD bit11, debounce 10/25/250); PC5 is
  state-*change*-triggered behind a long debounce (`0x2000daae`). Their content is
  debounce timing (micro-test), not a vector table — so no oracle-vector
  reimplementation like the transfer pair.

[`docs/18`](18-power-path-relays.md) names 6 relay pins and 4 logic functions;
we mirror 2 contracts (run-enable PC6, manual override PA12/PB3). The rest is
missing:
- Grid↔EPS **transfer sequencing**: order, inter-relay delays, the
  break-before-make gap. These are timing boundaries, so micro-test the delays.
- The **generator / AC-couple** relay and **EPS / dry-contact** pin conditions
  (HR 146 LineMode, IR 77, gen registers).
- **Oracle:** with T02 in place, drive state transitions through the bank and
  capture GPIO edge timestamps on the factory. Assert ordering and timing
  within tolerance.

> **The 2026-11-07 "release" (T14a blocked on the enable derivation) is now
> superseded** — the AC-transfer state→relay map is cracked and reimplemented (see
> the **Done** section above). The enable *provenance* (`sub_0801887c`) and the
> debounce *sequencing* are the remaining pieces, with PC5/PD11 next.

### T15 — Charge/discharge schedules with SOC/voltage gates (HR 64-89, 158-169)
**Status:** 🚧 `[~] claude 2026-11-07` — **discharge-by-voltage AND discharge-by-SOC hysteresis gates cracked + reimplemented + factory-verified**; discharge-controller wiring + HR 64-89 window schedules remain ([`docs/41`](41-charge-discharge-schedule-gates.md)) · **Layer:** **micro (window × SOC × V boundaries)** + sim · **Independent**

**Done (voltage gate, 2026-11-07).** The discharge-control gate (HR 120
**DischgCtrlType**) by-voltage path is a **latched hysteresis** on battery
voltage — `active = active ? (V >= stop) : (V >= start)`, V = safety-bank V `/10`,
start/stop at `settings+0x46/+0x48`. Reproduced as the pure
[`inv_dischg_volt_gate()`](../src/sched/dischg_gate.c) (host test
[`test_dischg_gate.c`](../tests/test_dischg_gate.c)) and **verified byte-for-byte
against the factory evaluator** driven in isolation
([`test_dischg_gate.py`](../tests/test_dischg_gate.py) +
[`dischg_gate_contract.py`](../tests/dischg_gate_contract.py), wired into
`make test-sim`). The verdict byte is consumed by the main power-control function
(literal-pool xref — so not dead). Details + the correction of the earlier draft in
[`docs/41`](41-charge-discharge-schedule-gates.md).

**Re-pinned to the canonical 07 image (2026-11-07).** The oracle now drives the
**07** image (`ceaa-07xx_vE_260214.bin`, per [`reference/README`](../reference/README.md)):
voltage-gate block `0x080355c2…0x08035608`, verdict `0x2000dbc3`, settings
`0x2000c85c`, bank `0x2000ce5c` — the self-contained block driven with `r1` =
settings base (the full evaluator `0x08035474` additionally gates on a health bit +
mode before reaching it). Same hysteresis, same offsets (`+0x46/+0x48/+0x0a`); the
earlier run used the ambiguous `com_flat.bin` (05-style addresses). Verified
byte-for-byte on the 07 image.

**Done (SOC gate, 2026-11-07).** The discharge-by-**SOC** path (DischgCtrlType mode 1)
is the **same latched hysteresis** on the battery SOC byte — `active = active ? (soc
>= stop) : (soc >= start)`, unsigned, thresholds `settings+0x4a/+0x4b`, SOC from the
relayed struct `0x2000d7b0+0`, verdict `0x2000dbc4` (the sibling of the voltage
verdict `0x2000dbc3`). Self-contained block `0x08035616…0x08035662`. Reproduced as
[`inv_dischg_soc_gate()`](../src/sched/dischg_gate.c) (host
[`test_dischg_gate.c`](../tests/test_dischg_gate.c), 24 checks) and **verified
byte-for-byte** against the factory (`test_dischg_gate.py` `test_factory_soc_matches_spec`).
**Correction:** the mode-1 gate does **not** read the T11 battery-limit struct (an
earlier note's claim) — it uses settings thresholds + the relayed SOC byte, so it has
no T11 dependency (docs/41 "The SOC half").

**Remaining:** wiring the gate verdicts into a discharge controller (none yet in
ours — the factory consumer is the main power-control function; overlaps T14/relay +
BMS-switch control); the HR 64-89 **time-window** schedules (charge-priority /
forced-discharge / AC-charge-SOC are **inert / not dongle-writable** on this image,
so they can't be configured or oracled here — blocked pending the features being
exposed).

**Finding ([`docs/41`](41-charge-discharge-schedule-gates.md)).** The three
schedule features' "active now" verdicts are computed by one combined ARM
evaluator `sub_0801ed28` (decoded on the **05-series** image; the committed 07
image's AC-charge window evaluator is `0x08034590`), writing three bytes
`0x2000aa5f/60/61` (05-image addresses; AC-charge / charge-priority / forced-discharge), gated by a
per-feature master-enable (`settings+0x23`), the HR 120 mode bits (`settings+0x33`),
the window, and SOC/limit/status inputs — i.e. literally **window × SOC × V**. But:
- Driven in isolation, the AC-charge verdict `0xaa5f` tracks the **feature-enable**,
  not the time window: the **ARM pushes the AC-charge windows to the DSP** (block 4,
  T10) and the **DSP** time-gates them. (Contrast AC-First, which the ARM evaluates
  itself → IR 126 bit 8.)
- Per the T10 capture, **HR 67 (AC-charge SOC) and HR 74-89 (charge-priority +
  forced-discharge) are inert** (not dongle-writable) on this image, so those gates
  can't be configured, exercised, or oracled here.

So **ours already covers the live ARM schedule duties** on this image (AC-First →
IR 126 bit 8; AC-charge windows → DSP block 4) and deliberately does not implement
the inert/DSP-gated paths.

**Done this pass:**
- Fixed `tests/timewindow_contract.py` so the `acchg` micro-test **skips cleanly**
  (was reported as ERROR) on images without its evaluator. Its evaluator
  (`0x08034590`) is present in the committed `ceaa-07xx_vE_260214.bin`, where the
  test **passes** (`test_acchg_factory_*`); it is absent from the older 05-series
  image, where the test skips.

**Hand-offs (see [`docs/41`](41-charge-discharge-schedule-gates.md) §Hand-offs):**
- The evaluator likely reads the **committed slot records** (`0x2000a330…`), not raw
  settings — pin that to drive the time/SOC gate in isolation.
- An image that exposes HR 67 / 74-89 (e.g. `ceaa-07xx_vE_260214`) to exercise the
  inert features and run the `acchg` oracle.
- The SOC gate reads the derived **battery-limit struct** (`0x2000a68c`) — **T11**.
- Trace where `0x2000aa5f/60/61` are consumed (relays / status IR / DSP).
- HR 126-131 OptimalChg is **dormant in the factory** (docs/31 Q5). Don't
  implement it beyond the existing round-trip unless that verdict changes.

### T16 — Generator: charge start/stop, quick start, warm-up/cool-down (HR 194-198 + 07-series)
**Status:** ⬜ `[ ]` · **Layer:** micro (thresholds/timers) + sim · **Soft-depends:** T14 (gen relay)

[`HR194_198`](wiring/ARM-UART5-dongle/HR194_198-generator-charge.md) start/end V/SOC and
max gen charge current, plus the 07-series additions
([`docs/11`](11-12000xp-revisions.md) #1 gen charge time scheduling, #2 quick
start 20-min cycle, #3 warm-up/cool-down, #15 no gen charge while Smart Load is
active). First locate the backing registers/settings for the 07-only features
(they may be outside the published spec). Write them up in `docs/wiring/ARM-UART5-dongle/`,
then oracle the start/stop thresholds and timers at their boundaries.

### T17 — Remaining 07-series features: Smart Load, Resume SOC, Quick Charge, buzzer
**Status:** ⬜ `[ ]` · **Layer:** RE + micro + sim · **Independent**

From [`docs/11`](11-12000xp-revisions.md): #6 Quick Charge (start, system
charge SOC/V limit), #7 discharge-resume threshold (+5 % / +2 V hysteresis,
which is a natural micro-test), #9 battery warning buzzer (find the GPIO via
[`docs/16`](16-arm-io-map.md)), #11 Smart Load power display (Psmart / Peps_port /
Pgrid_side: which IRs?). One agent can take each feature. Each needs the
register/setting located, a factory oracle, then ours.

### T26 — Document + test the spec-only (`idx`) registers
**Status:** ⬜ `[ ]` · **Layer:** RE + sim · **Independent** (split by group; one agent per group is fine)

These spec registers have **no file** in `ARM-UART5-dongle/` and no test:
**HR** 63, 92-97, 104, 106-109, 114-119, 121-125, 132-144, 149-151, 158-193;
**IR** 108-112. Some of them are **already persisted** by T03 (HR 107,
109, 119, 151) without a doc. For each group:
1. find the factory getter/setter case;
2. classify it as live / persisted / pushed to DSP / dormant (T23 and T25
   give most of this);
3. write the register file in the house format (meaning, provenance,
   side-effects, `## Test coverage`);
4. add it to the T24 vectors.

HR 158-169 overlaps T15 and HR 170-193 overlaps T19. Coordinate through those
cards rather than duplicating. AFCI IR 140-152 stays with T19.

### T27 — Input registers that still have no test
**Status:** ⬜ `[ ]` · **Layer:** sim (extend the bank/CAN contracts) · **Independent**

As of the audit, these input registers have no test at all:
- **IR 6 InternalFault**: T06 publishes it (classifier output), but no
  register-level serve test exists. Add it to the classifier e2e test.
- **IR 77 ACInputType** (grid vs generator): find the source (a bank field? a
  HR 146 LineMode derivation?), then factory-oracle it.
- **IR 127-138 EPS split-phase** (L1N/L2N V, P, S, E): [`docs/33`](33-usart2-telemetry-bank.md)
  says IR 127/128 come from the bank, so extend `SAFETY_TELEMETRY`. The P/S/E
  entries are probably ARM-computed, so extend the T07 telemetry contract. The
  E (energy) entries belong with the energy channels below.
- **Energy counters beyond Epv1**: `test_energy.py` covers only the PV1
  channel. Cover all ten channels (IR 28-37 day, 40-59 all), the 32-bit
  low/high carry at `0xFFFF → 0x10000`, and gating per state. The
  boundary-heavy parts (carry, rollover) suit a micro-test.
- **IR 108 T1** (12K BT temperature): live or dormant on `ceaa-07xx`?
- IR 71-75 (AutoTest) and IR 113 (ParallelInfo) stay with **T19**.

---

## P3 — later / lower leverage

### T18 — Firmware-update pass-through (`0x21/0x22/0x23`, State = Programming)
**Status:** ⬜ `[ ]` · Layer: sim. The ARM relays DSP firmware updates
([`wiring/ARM-USART3-DSP/bootloader-21_23`](wiring/ARM-USART3-DSP/bootloader-21_23.md)) and reports
IR 0 = `0x02`. Needed eventually so that field updates of the DSP keep working
under our firmware. Our own ARM update path (the bootloader layout in docs/11)
is a separate, later question.

### T19 — Grid self-test (AutoTest, HR 98 / IR 71-75), parallel systems (HR 112-114, IR 113), AFCI (IR 140-152)
**Status:** ⬜ `[ ]` · Mostly hybrid/region-specific and likely inactive on a
standalone 12000XP. First **prove whether each one is live on `ceaa-07xx`**
(the getter returns constants? a setter with no effect?), then record "dormant"
the way HR 126-131 was handled (`92d8e49`). Implement only what is live.

### T20 — Variant parity (18kPV `FAAB`, 6000XP `ccaa`)
**Status:** ⬜ `[ ]` · Re-run the oracle suites against the other App images
(hash table in `README.md`) once the 12000XP suites are broad. That needs the
per-image `PROFILES` approach of `timewindow_contract.py` generalised across
tests. Note: `lxp-factory` currently holds only the `ceaa-07xx` ARM image.

### T21 — Hardware bring-up checklist
**Status:** ⬜ `[ ]` · Once T01/T03/T05 land, write the bench procedure: flash
layout vs the 07 bootloader (vectors at `0x08005000`, docs/11; our 12000XP
link script is still monolithic at `0x08000000`, so decide which), panel init,
RS-485 DE, CAN bitrate. Also cover how to recover a unit that bricks.

---

## Cross-cutting, always-on

- **Coverage bookkeeping:** every task above that touches a register updates
  that register's `## Test coverage`. This is now enforced: **`make test` runs
  `tools/reg_coverage.py --check`** (T22), which fails if a test covers a register
  whose doc doesn't record it. Use **`make coverage-report`** for the register ×
  test matrix and the live "N of 54 files list no test" figure — don't hand-count.
- **Harness speed:** sim tests get slower as they grow. Any agent that adds a
  sim test should reuse the warm-once / clone-per-case pattern
  ([`docs/19`](19-gpio-test-harness.md) §"Warm once, clone per case") and
  prefer a micro-test for boundary sweeps.
- **Quirks:** add each new docs/31 entry *as soon as you see it*, even while
  your task is still in flight.

## Dependency sketch

```
T01 UART5 ─────────────┐
T02 RTOS tasks in sim ─┼─> T05 USART2 RX ─┼─> T08 link supervision ─┐
                       │   T09 USART3 RX demux ✓ (Modbus/bootloader; no 0x49) │
                       │                  │                         ├─> T13 dashboard (real data)
T06 classifier ────────┼──────────────────┴─────────────────────────┤
                       └─> T14 relays (needs T02 + T06) ─> T16 gen  │
T03 persistence ─> T12 identity/commands                            │
T04 validation   (independent)                                      │
T07 computed IRs (independent) ─────────────────────────────────────┘
T10 DSP blocks  <── T11 BMS limits (block 1)
T15 schedules, T17 07-series features   (independent)
```

Open and in-progress tasks are the ones still listed under P0-P3 above. Finished
tasks are in [Completed tasks](#completed-tasks) below.

---

## Completed tasks

Finished tasks, moved here from P0-P3 so the sections above show only open
work. Agents append newly finished tasks at the end (see "Claiming a task").
Each card keeps its original heading and ID.

### T01 — Move the dongle Modbus slave to UART5 (ours + harness)
**Status:** ✅ `[x] claude/019chjb 2026-11-06` · **Layer:** sim (common) · **Unblocks:** T08, all hardware use

> **Done.** Ours now serves Modbus on **UART5** (`src/uart/uart5.c`, PC12/PD2,
> RS-485 DE on PA15), rebound in `src/modbus/modbus_port.c`; USART3 is the DSP
> link's alone (`src/dsp/dsp_link_port.c` brings it up). The harness
> `ModbusDongle` auto-detects the port. **Oracle finding:** the factory answers
> on **USART3** in the harness, **not** UART5 — its UART5 receive path
> (`sub_0802afe2`) is a scheduler task that needs the RTOS running (**T02**);
> the USART3 register model it serves is the same, so it is a valid oracle
> meanwhile (and probing UART5 on the factory is avoided — its ISR disturbs
> persistence). `make test-sim` green for both images (common 9/9 each, verified
> on the committed `reference/ceaa-07xx_vE_260214.bin` — the 07-series factory
> oracle). DE sequencing pinned by
> `test_modbus_de_toggles_around_tx`. Docs: README port note, [`docs/04`](04-modbus.md),
> [`docs/wiring/ARM-UART5-dongle`](wiring/ARM-UART5-dongle/README.md). The full UART5
> oracle for the factory is a **T02 follow-up**.

Today our Modbus engine and the DSP config push **share USART3**, so on real
hardware the dongle can never reach us. The factory serves the dongle on
**UART5 + RS-485 DE on PA15** ([`wiring/ARM-UART5-dongle`](wiring/ARM-UART5-dongle/README.md),
[`docs/26`](26-dongle-firmware.md)).
- **Oracle:** teach `tests/arm_sim_modbus.py` (`ModbusDongle`) to drive
  **UART5** (`0x40005000`). Prove that the factory answers a read on UART5 and
  that DE toggles around TX. Pin the factory's UART5 baud and RX mechanism
  (docs/26 notes UART5 is polled or handled by a task, not NVIC-vectored as
  USART3 is). Keep a USART3 mode only if the factory demonstrably answers
  there, and record that in `wiring/ARM-UART5`.
- **Ours:** add a UART5 driver, rebind `modbus_port.c` to it, and drive DE in
  `mb_port_set_tx()`. Leave USART3 to the DSP alone. Then every existing common
  test must pass unchanged over UART5.
- **Done when:** `make test-sim` is green for both images with the dongle on
  UART5, and the README "Port note" plus docs/04 are updated.

### T02 — Run the factory's RTOS tasks in the simulator  (split into T02a / T02b)
**Status:** ✅ `[x] claude-opus/019chjbE 2026-11-07` · **Layer:** harness (`tools/arm_sim.py`) · **Unblocks:** T05, T08, T14, wire-level e2e

**Done** (both halves). Split into two cards (ID kept for references):
- **Scheduler + the relay/control task run** under `enable_rtos()` +
  `attach_config_flash()` — proven ([`docs/19`](19-gpio-test-harness.md)
  §"The factory runs a preemptive RTOS").
- **T02a** (USART2 bytes → IR) **done**; **T02b** (state → PC6) **done**. Full
  cracked chain, the frame-trust gate, and the inverter-health inputs that gate PC6:
  [`docs/19`](19-gpio-test-harness.md) §"T02", [`docs/33`](33-usart2-telemetry-bank.md),
  [`docs/18`](18-power-path-relays.md).

#### T02a — Feed the USART2 safety link on the wire → bank/IR
**Status:** ✅ `[x] claude-opus/019chjbE 2026-11-06` · **Layer:** sim (factory) · **Unblocks:** T05, T02b

**Done.** A raw USART2 safety frame fed on the wire — through the factory's *real*
RXNE ISR, byte by byte — is assembled, CRC-checked, distributed and tag-parsed by
the firmware into its telemetry bank, and the decoded measurements come back out
as the right Modbus input registers, with **no bank seeding**.
`test_usart2_frame_reaches_modbus` feeds a tag-2 frame and reads IR 12/15/20/18/13
(grid R/freq/EPS R/inverter current/grid S) back, tracking across frames.
- **Chain cracked** (verified statically + executed, docs/33 §1): RXNE IRQ
  `sub_0801bddc` → assembler `sub_0801bb0e` (SOF `0x49`, `frame[3]`=len,
  CRC-16/MODBUS big-endian) → validator `0x08027560` → distributor `sub_0802677a`
  + tag parser `sub_08025ab8` → bank **`0x2000ce5c`** → the factory's getter.
- **Two data fixes it forced:** the telemetry bank is `0x2000ce5c`, **not**
  `0x20009e54` (zero refs — a mis-transcription that had `FAC_SAFETY_BANK` wrong,
  so `test_safety_cpu_telemetry_reaches_modbus` was failing; now fixed and green);
  and docs/33's parse-chain function addresses were wrong (the field-offset map was
  right). Root cause of the earlier dead end: a disassembler base off by `0x5000`
  (docs/19 §T02). The reusable feeder adds `build_frame()`/`feed_frame()` for T05.
- **Gating note for T02b:** mode/fault/warn (`BANK+0/+0xd0/+0xd4`) are published
  only once the frame-trust counter `0x2000da3e` reaches `0x54`; measurement/ID
  tags are ungated (published every valid frame).

#### T02b — Change operating state → PC6 moves (via the running relay task)
**Status:** ✅ `[x] claude-opus/019chjbE 2026-11-07` · **Layer:** sim (factory) · **Depends:** T02a

**Done.** A USART2 operating-mode byte fed on the wire drives **PC6** (the run-enable
relay), end to end through the factory's real RTOS, with **no internal-function
call**: `test_usart2_mode_drives_pc6` asserts running modes close PC6 (=1) and
standby/fault/programming open it (=0). The full chain, all pinned and executed:

```
frame[+4] (mode) → bank+0 → classifier sub_0801a678 → IR_STATE 0x2000d0e4+0xa0
                → relay decider sub_08016ec6 → PC6 = (IR_STATE >= 3)
```
- **Classifier = `sub_0801a678`** (NOT `sub_0801b480`, which is RTC housekeeping —
  docs/22). It writes IR_STATE (`0x2000d0e4+0xa0`, pass-through of the mode) and
  composes `STATE+0x98` (fault) / `STATE+0x9c` (warn) from `bank+0xd0/+0xd4`.
- **Decider = `sub_08016ec6`** (selector 2): clean path `PC6 = (IR_STATE >= 3)`,
  but it *blinks* (state-independently) when `STATE+0x98==0` **and** `STATE+0x9c!=0`
  (a warning, no fault); `0x2000da6c` bit 4 is a manual override.
- **The key to a clean demo: make the inverter healthy so `STATE+0x9c == 0`.** Two
  ARM-local warnings stand in a bare harness, both now understood and cleared from
  the wire/GPIO:
  - **W008 (FW-version mismatch):** the classifier case-insensitively compares
    `bank+3..6` against the string **"ceaa"** (`sub_0801a93a`); feed a tag-0 frame
    with that identity (`frame[+0x15..+0x18]`) → `health 0x2000d890` bit 10 sets →
    W008 clears.
  - **W006 (comms health):** gates on the **PD8 "detect" input** (docs/16: GPIOD
    bit 8, read by `sub_0801ac2c` via `sub_8014fb0` with a ~10-tick debounce) **and**
    `bank+0xca` bit 0. Drive PD8 high (`set_input`) + feed clean telemetry → W006
    clears.
  With both clear the decider's clean path runs and PC6 tracks the fed mode. (The
  frame-trust counter `0x2000da3e` is seeded warm, ~85 frames reach it, as the serve
  test seeds the bank; the mode byte itself travels the full real wire path.)
- **This corrects the earlier (over-pessimistic) note that clean PC6 was "not
  reachable from USART2 alone"** — it is, once the PD8 detect input is driven, which
  the GPIO harness does routinely (docs/18/19/22 updated).
- **Harness gotcha found:** between fed frames the assembler's ready flag
  (`buf+0x36a`) must clear, which needs the consumer task to run (~4M insns of
  settle); feed with `settle=0` + an explicit `sim.run()` to pace it.
- Pure harness work; changes no firmware.

### T03 — Persist the full pinned settings table (54 more registers)
**Status:** ✅ `[x] claude 2026-11-06` · **Layer:** sim (cross-image) + host · **Independent**

**Done.** Our firmware now persists the full pinned set via a const table
(`include/inv/settings_map.h`: HR → slot/offset/width/scale), driving both
`settings_persist_hr` and `settings_seed_hr` (`src/main.c`); `config_flash` gained
1-byte accessors for the packed slot-5 block. `tests/test_persist_crossimage.py`
is now table-driven (`tests/settings_persist_contract.py`) and green both ways:
ours→flash over the **whole table**, byte-exact to the factory layout and
byte-identical to the factory's own record per storage class; and factory→ours
*live* round-trip one register per storage class. **62 registers** covered
(docs/23's 56 + the 6 AC-First windows newly pinned here). A full-table *live*
ours→factory read-back is blocked on **T02** — the factory RTOS re-journals on boot
and wedges the dongle when it boots on a device we have written (see docs/23
"Harness note"). The oracle settled three docs/23 errors/notes — slot-5 `+0x00..+0x07`
are **1-byte** fields, HR 109 is at **+0xa5** (not +0xa4), and two factory
behaviours (HR 21 `FuncEn` read-merge, HR 112 slave-mode write gating) → docs/31
Q8/Q9. Still gated (follow-up, as docs/23 predicted): the charge-first /
forced-discharge schedules (74, 76-89) and the Q(V)/PF block — they draw no `0x06`
echo without a precondition. See [`docs/23`](23-arm-config-writer.md) "Width
correction & harness notes".

[`docs/23`](23-arm-config-writer.md) pins **56 HRs** to slot-0/slot-5 offsets,
widths and `×10` scalings, all dynamically. We persist 2.
- **Oracle:** generalise `tests/test_persist_crossimage.py` into a **table-driven**
  test over the full docs/23 table: write → cold boot → read back, **ours→factory
  and factory→ours**. It already shares the SPI-flash model, so a record written
  by one image must read back correctly in the other.
- **Ours:** replace the `switch` in `settings_persist_hr` / `settings_seed_hr`
  with a **const table** (`include/inv/settings_map.h`: HR, slot, offset, width,
  scale). Keep slot-1↔4 mirroring and the internal-flash mirror for slots 0/5 in
  mind (docs/23 §"Slot 1 ↔ slot 4", §"Internal-flash mirror").
- Also find the slot/offset of the **schedule** HRs (64-89, 152-157) and the
  **AC-First** windows if they aren't pinned yet, using the same probe method.
- Watch the odd offsets: `+0x13`, `+0x15`, `+0x1b` in slot 0, and the one-byte
  steps in slot 5 (`+0x00`, `+0x01`, `+0x02`…). A "2B" field at a 1-byte stride
  means the docs/23 widths may be wrong for some rows. **Settle this with the
  oracle before trusting the table**, and correct docs/23 if needed.

### T04 — Holding-register write semantics: ranges, clamps, rejects, read-only
**Status:** ✅ `[x] claude 2026-11-06` · **Layer:** micro (per-register vectors) + one sim smoke · **Independent**

**Done.** The factory **rejects** an out-of-range write with a Modbus exception
(it does **not** clamp or store): out-of-range → exception `3` (ILLEGAL_VALUE),
read-only register → exception `4` (SLAVE_FAILURE), reserved address → exception
`2`. Recovered by a fresh-boot-per-value dongle probe (the harness RX degrades
after a rejected write, so static isolation of the validator wasn't needed and
wasn't achieved). Ours: `settings_validate()`
([`src/settings/settings_validate.c`](../src/settings/settings_validate.c),
[`include/inv/settings_validate.h`](../include/inv/settings_validate.h)) in front
of `mb_wr_hold` **and** `hmi_write` ([`src/main.c`](../src/main.c)). Tests: common
[`tests/test_settings_validate.py`](../tests/test_settings_validate.py) +
[`settings_contract.py`](../tests/settings_contract.py) (factory + ours agree, 11
vectors), host [`tests/test_settings_validate.c`](../tests/test_settings_validate.c)
(`make test`). Deviations → [`docs/31`](31-factory-quirks.md) **Q6** (HR 101/105
enforce only one bound — replicated for parity) and **Q7** (HR 22 returns
exception 2 on this image). Register coverage updated for HR 9/10, 15, 20, 22, 66,
101, 105.

Original card:

`mb_wr_hold` accepts anything (`/* TODO: validate ranges */`). The factory's
behaviour on an out-of-range write is **unknown**: reject with exception 3,
clamp, or store verbatim.
- **Oracle:** a table-driven sim test sweeps each documented HR at `min-1`,
  `min`, `max`, `max+1` (ranges from `modbus_map.h` / the per-register docs) and
  records the reply (echo vs exception code) plus the read-back value. Also
  cover writes to **reserved** and **read-only** addresses, and `0x10` on
  registers other than SN/time (the spec says `0x10` is only valid for SN and
  time; does the factory enforce that?). Sweeping the vectors may be cheaper as
  a micro-test of the factory's per-register setter, if one is isolatable.
- **Ours:** a `settings_validate(reg, val) → {accept, clamp(v), reject(exc)}`
  pure function in front of `mb_wr_hold` **and** `hmi_write`.
- Every deviation from the spec range goes into docs/31.

### T05 — USART2 safety-CPU receiver: wire frame → bank
**Status:** ✅ `[x] claude-opus/019chjbE 2026-11-07` · **Layer:** host (parser) + sim (wire e2e) · **Depends:** T02 (landed)

**Done.** Our firmware now fills the telemetry bank from the wire and serves it,
byte-for-byte compatible with the factory (the same raw USART2 bytes produce the
same Modbus input registers on both images).
- **Parser** (`src/safety/safety_rx.c`, `inv/safety_rx.h`): a pure, host-tested
  byte-stream state machine for the EG4 type-1 frame (SOF `0x49`, `frame[3]`=len,
  total `len`+6 capped `<0x40`, CRC-16/MODBUS big-endian). It validates the CRC and
  type, distributes the header (mode / relayed fault+warn / etc.) and the tag
  sub-record (docs/33 §1a, tags 0/1/2) into the bank (native LE, as
  `safety_cpu_publish` reads it), and resynchronises past garbage. Host test
  `tests/test_safety_rx.c` (37 checks): good/bad CRC, wrong type, truncated,
  unknown tag, resync after junk, and each tag's field map.
- **Driver** (`src/uart/uart2.c`, `inv/uart2.h`): RXNE-interrupt USART2 (PA2/PA3,
  RS-485 direction PC2, docs/16), matching the factory (RXNE, not DMA — docs/19
  T02). The glue `src/safety/safety_rx_port.c` drains the RX ring, feeds the parser
  into `g_safety_bank`, and exposes the decoded mode/fault/warn to the classifier
  (wired into `main.c`; `state_publish` now flows the real mode/fault/warn out).
- **Oracle:** the common sim test `test_usart2_safety_frame_reaches_modbus`
  (tests/test_arm_sim.py) feeds the **same raw tag-2 frame** to both images and
  asserts IR 12/15/20/23/18/13/122 — ours (UART5 Modbus) and the factory (USART3,
  via the T02 USART2 wire feeder) serve identical values. Both green.
- **rx-timeout → fault (for T08):** `safety_rx_last_frame_ms()` /
  `safety_rx_link_ok(now, timeout)` expose link liveness; T08 maps a stale link to
  the comms-loss fault (E017). Left as the hook, not the policy, per T08's scope.

### T06 — Operating-state classifier + fault/warning composer (`sub_0801a678`)
**Status:** ✅ split → **T06a `[x]`** (ours + host), **T06b `[x]`** (factory oracle, T02b-unblocked 2026-11-07) · claude · **Layer:** **micro** + sim e2e · **Unblocks:** T13, T14

- **T06a `[x]` ✅ — our classifier + host oracle (done).** Pure
  `inv_classify(mode_byte, relayed_fault, relayed_warn, local_flags) →
  {state, fault32, warn32}` (`include/inv/classify.h`, `src/state/classify.c`):
  canonicalised pass-through of the mode byte (Table 9 + LCD Bypass 0x11/0x19),
  fault/not-running override, and the FaultCode/WarningCode composition (relayed
  word + ARM-local E000/E017/W008, E027 passes through) per IR000 / IR060_063.
  Host-tested (`tests/test_classify.c`, `make test`, 63 checks). Wired into
  `main.c`: IR 0 + IR 60-63 are now published **through the classifier** instead
  of a hard-seeded Standby (`state_publish()`), so the real mode/fault/warn flow
  out to Modbus as soon as the USART2 ingest feeds them.
- **T06b `[x]` ✅ — factory oracle (done, T02b-unblocked).** With the USART2 wire
  running (T02b) the classifier is pinned on the 07 image: **IR 0 is a pure
  pass-through of the relayed mode byte** — no canonicalisation, no fault override.
  Proven by feeding mode bytes on the wire and reading IR_STATE (`0x2000d0e4+0xa0`):
  every byte 0x00–0xFF appears verbatim (canonical, LCD 0x11/0x19, and arbitrary
  bytes 0x55/0xFF alike), and a relayed fault flows to the FaultCode (IR 60/61)
  **without** changing IR_STATE. This **corrected both of docs/22's 05-series
  guesses** (no 0x02 override target, no 0x08 non-canonical default) and
  `inv_classify` was fixed to match (canonicalisation + override removed, the
  `INV_LOCAL_NOT_RUNNING` flag dropped). Classifier = `sub_0801a678`, bank base
  `0x2000ce5c`, all re-pinned in T02a/T02b. Tests: `test_usart2_classifier_is_pure_passthrough`
  + `test_usart2_mode_reaches_ir_state` (factory), `test_usart2_mode_classified_passthrough_e2e`
  (ours), `test_classify.c` (host). The isolated-call `ClassifyBackend` the card
  envisioned proved unnecessary (the deciders fault when called in isolation —
  docs/18); the wire-fed e2e is the oracle. See [`docs/22`](22-arm-dsp-core-split.md)
  "T06b RESOLVED".

[`docs/22`](22-arm-dsp-core-split.md) says the ARM's mode module is a
**classifier, not a power FSM**:
`received_mode_byte + fault flags → IR_STATE`, plus a merge of the relayed
fault/warn words with ARM-local bits (E000, E017, W008, low warn bits 0-9; see
[`IR060_063`](wiring/ARM-UART5-dongle/IR060_063-FaultCode_WarningCode.md)).
- **Oracle:** a micro-test calls `sub_0801b480` in isolation and sweeps **every
  mode byte 0x00-0xFF** × {no fault, each ARM-local fault bit, relayed fault}.
  It records the IR 0 / 6 / 60-63 outputs as the vector table. Specifically
  check the manual's extra codes `0x11` Bypass and `0x19` PV-charge+bypass
  ([`IR000-State`](wiring/ARM-UART5-dongle/IR000-State.md)), and what an
  unknown/non-canonical byte becomes.
- **Ours:** `inv_classify(mode_byte, relayed_fault, relayed_warn, local_flags)
  → {state, fault32, warn32, internal_fault}` as a pure function. Publish it
  from `main.c` instead of the hard-seeded Standby.
- **Sim e2e:** inject a bank mode byte plus fault bits, then read IR 0/60-63
  over Modbus on both images.

### T07 — ARM-computed telemetry registers
**Status:** ✅ `[x] claude 2026-11-06` · **Layer:** micro (scaling/rounding) + sim · **Independent** (sources may be injected)

**Done (serve layer).** The computed power registers are served from a 32-bit
value the ARM keeps internally in **0.1 W**, as `IR = (uint16_t)(internal / 10)` —
unsigned, truncating, **not a float** (this *corrects the card's "float" guess*,
recovered by injecting the STATUS-struct source and reading the getter
`sub_0803289c`). Covered: **IR 7/8 Ppv**, **10/11 Pcharge/Pdischarge** (the getter
adds no sign clamp — the split is upstream), **16/17 Pinv/Prec**, **24 Peps**,
**26/27 Ptogrid/Ptouser** (all `/10`); **IR 25 Seps** served **1:1** in VA; **IR
69/70 RunningTime** a u32 seconds counter split low/high (advances 1/s while
`op_state ≥ 3`). Ours: `inv_telemetry_publish()`/`inv_power_to_ir()`
([`src/telemetry/telemetry.c`](../src/telemetry/telemetry.c),
[`include/inv/telemetry.h`](../include/inv/telemetry.h)), wired into
[`src/main.c`](../src/main.c) and feeding `src/energy/`. Tests: common
[`tests/test_telemetry.py`](../tests/test_telemetry.py) +
[`telemetry_contract.py`](../tests/telemetry_contract.py) (factory + ours agree),
host [`tests/test_telemetry.c`](../tests/test_telemetry.c). Register coverage
updated for IR 7-11, 16-17, 24-27, 69-70.

**Deferred (the V·I / sign-split COMPUTE itself).** The getter only *serves* a
pre-computed value; the upstream compute is filled by the **safety-CPU `0x49`
telemetry parser on USART2** (`sub_08025ab8` over buffer `0x20009048`, a scheduler
task that doesn't run in the harness) — so the internal quantities are
**injected** here (as the card allows) and the real compute lands with the
**USART2 ingest, T05** (*not* a USART3 `0x49` — the ARM's USART3 RX is a
Modbus/bootloader demux, see **T09**).

**T07b update (2026-11-07, after T02a landed the USART2 ingest).** The two
bank-**relayed** fields are now served from the safety bank by `src/safety/safety_cpu.c`:
**IR 19 PF** (bank `+0xaa`, raw 0-2000 verbatim — [`IR019-PF`](wiring/ARM-UART5-dongle/IR019-PF.md))
and **IR 107 BatVoltSample_INV** (bank `+0x0a`, 0.1 V), both added to the shared
`SAFETY_TELEMETRY` contract (ours proven by `test_arm_sim_self_only.py`; the factory
oracle validates them against its getter when run on a ceaa-07xx image).
**Correction:** **IR 64 Tinner / 67 Tbat** and **IR 77 ACInputType** are **not** in
the recovered USART2 safety bank (docs/33's tag map carries only the radiator temps
IR 65/66 — no inner/battery temp, no AC-input-type). So they are **not**
bank-relayed on this image; their source is elsewhere/unrecovered — a correction to
the earlier "relayed per docs/33" assumption. RunningTime cross-boot persistence is
still open (T07b).

Original card:

These are the registers the ARM **computes** rather than relays
([`docs/22`](22-arm-dsp-core-split.md) "PV power is ARM-computed",
[`docs/33`](33-usart2-telemetry-bank.md) §3). Find each register's inputs and
formula from its factory getter, then oracle it:
- **IR 7-9 Ppv** (V·I, float in the factory, so check rounding/truncation and
  the negative/zero clamp), **IR 10-11 Pcharge/Pdischarge** (sign split of the
  battery power), **IR 16-17 Pinv/Prec**, **IR 24-25 Peps/Seps**,
  **IR 26-27 Ptogrid/Ptouser**, **IR 19 PF** (encoded range).
- **IR 69-70 RunningTime** (what increments it, gating state, does it persist
  across boot?), **IR 77 ACInputType**, **IR 107 BatVoltSample_INV**,
  **IR 64 Tinner / IR 67 Tbat** (if ARM-local ADC).
- Each formula gets a micro-test over its edge vectors (0, negative, rail,
  overflow of the u16). Then a single sim test checks that the whole set is
  served after one injected snapshot.
- These feed `src/energy/` (it already integrates `IR_PPV*` etc.), so once they
  are real, the energy counters ([`docs/37`](37-energy-accumulation.md)) are
  real too.

### T09 — DSP link RX: what the ARM consumes on USART3 (finding corrects the premise)
**Status:** ✅ `[x] claude 2026-11-06` ([`telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md), [`dsp_rx.c`](../src/dsp/dsp_rx.c), [`test_dsp_rx.py`](../tests/test_dsp_rx.py)) · **Layer:** host + sim · **Independent**

**Finding: the ARM does NOT parse a `0x49` telemetry frame on USART3.** The
premise ("the factory parses DSP `0x49` on USART3", with RX path
`FUN_0801bb0e`/`FUN_08025ab8`) was wrong — those are the **USART2** safety-CPU
`0x49` path. The ARM's USART3 RX (ISR `sub_0801c774` → `sub_0801c6e0` → byte
handler `sub_0801c3e6`, buffer `0x20007490`) is a **Modbus-slave (`03/04/06/10`)
+ DSP-bootloader (`21/22/23`) demux**, address-gated; a `0x49`/type-1 frame is
rejected. Proven static (App vector table + `tools/disres.py`: the func dispatch,
and the `cmp #0x49` living in the USART2 handler `sub_0801c808` reading buffer
`0x20009048`) **and** dynamic (the real byte handler drops a `0x49` SOF while
assembling Modbus/bootloader).
- **Oracle (done):** drive the real `sub_0801c3e6` with each frame's first two
  bytes and check whether the assembler advances (accept) or resets (drop) —
  [`tests/dsprx_contract.py`](../tests/dsprx_contract.py)`::FactoryBackend`.
- **Ours (done):** [`inv_dsp_rx_classify`](../src/dsp/dsp_rx.c) mirrors the demux
  decision (pure, host-tested [`test_dsp_rx.c`](../tests/test_dsp_rx.c)); the
  USART3 RX service [`src/dsp/dsp_rx_port.c`](../src/dsp/dsp_rx_port.c) drains the
  wire, serves Modbus as a slave (the DSP polls the ARM here), recognises
  bootloader frames (→ T18), and drops the rest. Wired into `src/main.c`.
- **Recorded** in [`telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md)
  (rewritten), the USART3-DSP [`README`](wiring/ARM-USART3-DSP/README.md) /
  [`fields`](wiring/ARM-USART3-DSP/fields.md) (corrections folded in) and
  [`docs/31`](31-factory-quirks.md) Q10. Common sim test wired into `make test-sim`.
- **Consequence for telemetry compute (T07 follow-ons):** the upstream V·I /
  sign-split compute does **not** arrive via a USART3 `0x49` — its source is the
  **USART2** safety-CPU telemetry bank (docs/33). Re-point IR 19/64/67/77 work at
  T05 (USART2 ingest), not at this task.

### T11 — BMS: charge/discharge limit derivation + inverter→BMS TX
**Status:** ✅ `[x]` (all three) → **T11a `[x]`** (charge-V working limit), **T11b `[x]`** (inverter→BMS TX), **T11c `[x]`** (quirks Q1-Q4 as tests) · `claude/019chjb 2026-11-07` · **Layer:** micro (clamp math) + sim (CAN e2e) · **Independent**

Split after the T11a oracle came back much smaller than the card assumed: the
only BMS "limit derivation" the factory exposes (reachably, in the harness) is the
charge-voltage one, and it is a plain `min` with a setting, not a multi-field
cell-count computation. The current/discharge fields and the inverter→BMS TX need
the RTOS tasks (T02) to observe, so they were carried as T11b/T11c. **T11b is now
done** (T02 landed): the inverter→BMS TX is a `0x305` DLC8 all-zero keep-alive that
ours already matches. The IR 81/82/84 current/discharge fields turned out to be a
genuine map gap on this image (still `0` with the RTOS running), not T02-gated.

#### T11a — BMS charge-voltage working limit (IR 83 = min(0x351, HR 99))
**Status:** ✅ `[x] claude/019chjb 2026-11-07` ([`bms_limits.c`](../src/bms/bms_limits.c), [`test_bms_limits.c`](../tests/test_bms_limits.c), [`ARM-CAN1-BMS`](wiring/ARM-CAN1-BMS.md#working-limit-derivation-t11a)) · **Layer:** micro (clamp) + sim (CAN e2e) · **Independent**

- **Finding (corrects the card):** the factory serves `IR 83 = min(0x351 charge-V
  limit, HR 99 ChargeVoltRef)` — a plain min, oracled black-box on `ceaa-07xx`
  (sweep `0x351` 0/100/560/600/1000 vs HR 99 520/574/590, all `min`). The
  "~57.4 V cell-count clamp" in the old `on_can_frame` comment is simply HR 99's
  power-on **default** (574); HR 99 = 590 raises the ceiling, so there is no
  separate hard clamp. **IR 81/82/84** (max chg/dis current, discharge cutoff)
  stay `0` under the same sweep — no reachable publish path; open pending T02.
- **Done:** pure fn `inv_bms_charge_volt_ref()`; host micro-test sweeps the `min`
  boundaries (13 checks); sim e2e `test_bms_charge_volt_ref_clamps_to_setting`
  (setting-wins branch) + the two `*telemetry*` tests (pass-through branch, HR 99
  raised over the wire) green for **both** images; docs in
  [`IR081_106-BMS`](wiring/ARM-UART5-dongle/IR081_106-BMS.md#working-charge-voltage-derivation-t11a),
  [`HR099_102`](wiring/ARM-UART5-dongle/HR099_102-leadacid-charge.md), [`ARM-CAN1-BMS`](wiring/ARM-CAN1-BMS.md).

#### T11b — inverter→BMS CAN TX (`0x305` keep-alive)
**Status:** ✅ `[x] claude/019chjb 2026-11-07` ([`test_can_tx.py`](../tests/test_can_tx.py), [`can_tx_contract.py`](../tests/can_tx_contract.py), [`arm_sim_can.py`](../tests/arm_sim_can.py) `capture_tx`, [`ARM-CAN1-BMS`](wiring/ARM-CAN1-BMS.md#inverter--battery-tx-t11b)) · **Layer:** sim (CAN TX capture) · **Was:** T02-blocked, now done

- **Finding (oracle, unblocked by T02):** with the TX task running under the RTOS,
  the factory transmits **`0x305`, DLC 8, payload all-zero**, once it has received
  pack telemetry, periodically, and **state-independent** (nominal vs faulted/low
  identical). No `0x300/0x301/0x400` in steady state. **Our firmware already sends
  exactly that** (`main.c` ~1 Hz keep-alive, `can_port.c`) — the "payload
  provisional" note was correct by luck and is now settled.
- **Done:** added a reusable bxCAN **TX capture** to the CAN harness
  (`arm_sim_can.py` `capture_tx` — presents TME, records each TXRQ; our firmware
  even *drops* the keep-alive unless TME0 reads set, so the capture is what lets
  ours transmit in the sim too); sim test `test_can_tx.py` asserts `0x305`/DLC8/zero
  for **both** images and that they agree; docs in
  [`ARM-CAN1-BMS`](wiring/ARM-CAN1-BMS.md#inverter--battery-tx-t11b).

#### T11c — BMS quirks Q1-Q4 as committed tests
**Status:** ✅ `[x] claude/019chjb 2026-11-07` ([`test_arm_sim_factory_only.py`](../tests/test_arm_sim_factory_only.py), [`test_arm_sim_self_only.py`](../tests/test_arm_sim_self_only.py), [`docs/31`](31-factory-quirks.md) Q1-Q4) · **Layer:** sim (factory-green / fixed-in-ours) · **Independent**

- **Done.** Each [`docs/31`](31-factory-quirks.md) verdict is now a committed test,
  factory-oracled on ceaa-07xx and asserted clean on ours:
  - **Q1** (`0x355` hi-res SOC → IR 101) + **Q2** (`0x359` "PN" → IR 97):
    `test_bms_frame_misfiling_quirks_q1_q2` reproduces them on the factory
    (IR 101 = 7700, IR 97 = 0x4E50, IR 96 module count correct);
    `test_bms_frame_misfiling_quirks_not_reproduced` asserts ours leaves IR 97/101
    at 0 while still publishing IR 96.
  - **Q3** (`0x35A` dropped): `test_bms_alarm_b_reaches_no_register_q3` (factory) /
    `test_bms_alarm_b_not_decoded` (ours) — inject only 0x35A, no IR 81-106 moves.
  - **Q4** (IR 98 unit): no new test — a unit-label question, not a value bug; the
    1:1 pass-through both images perform is already locked by
    `test_can_battery_telemetry_reaches_modbus`. Physical unit stays open (docs/31).

### T12 — Identity and command registers: HR 11, HR 15, SN (HR 2-6), FW versions (HR 9-10)
**Status:** ✅ `[x] claude 2026-11-07` · **Layer:** sim + host · **Depends:** T03 (persistence of addr / SN)

Done — HR 11 command dispatch, HR 15 live address change, HR 9/10 own-version
read-back + live DSP version, and W008 (identity compare) are implemented and
tested. W008 and the DSP-version read-back were pinned and proven once the USART2
wire ran (T02b); the HR 15 timing and wrong-SN behaviour remain decisions because
they live on the factory's **dongle UART5** slave task, which the sim does not
schedule (a separate factory-dongle harness — not T02, which is done).

- **HR 11 ResetSetting** ([`HR011`](wiring/ARM-UART5-dongle/HR011-ResetSetting.md),
  [`docs/23`](23-arm-config-writer.md) §Reset-to-default): **done.**
  `src/state/command.c` (`inv_command_apply`) dispatches one op per set bit,
  reboot last; it is a one-shot (register reads back 0). Wired: bit 0 clears
  energy/runtime counters, bit 5/6 drive the BMS charge/discharge switches, bit 7
  is a real `SCB->AIRCR` SYSRESETREQ (constants confirmed in the 07 image). Bits
  1/2/3/4 (defaults / adj-ratio / fault & monitor records) are accepted-and-ignored
  for now rather than faked (docs/23 open). Tests: [`test_command.c`](../tests/test_command.c)
  (24 checks), + one-shot over the wire in [`test_arm_sim_self_only.py`](../tests/test_arm_sim_self_only.py).
- **HR 15 ComAddr:** **done.** Ours adopts the new address after the write's own
  reply (deferred one transaction so the ACK lands on the old address), and loads
  the stored value on boot — no reboot. Address-0 broadcast and the factory's exact
  apply-moment are **not observable** here (factory-dongle UART5 task, not scheduled
  — not T02); our contract is "immediate, after the reply". Test:
  `test_comaddr_changes_slave_address_live`.
- **SN (HR 2-6):** persisted via T03 (`0x10` write-multiple); ours runs
  `check_sn=false` (SN echoed, not required to match). Whether the factory drops or
  excepts a wrong-SN frame is **not observable** (factory-dongle UART5 task, not
  scheduled — not T02); decision in docs/31 is to serve any correctly addressed frame
  rather than risk stranding a dongle.
- **HR 9-10 versions + W008:** **done, and pinned by T02b.** Ours seeds HR 9 high /
  HR 10 high from its own build constants (`OSS_ARM_COMMS_VER`, `OSS_FW_VERSION_CODE`)
  and now serves **HR 10 low live from the relayed DSP version** (`bank+2`), proven on
  the factory (`test_usart2_dsp_version_reaches_hr10_low`). **W008 is a model-IDENTITY
  compare** (not a numeric version compare): the classifier matches the relayed peer
  identity (bank+3..6) against "ceaa" and sets the version-OK health bit `0x2000d890`
  bit 10 — proven both directions (`test_usart2_identity_drives_version_health_bit`).
  Ours implements the same case-insensitive compare vs `model_code`, latched, raising
  W008 while unmatched (`src/safety/safety_cpu.c`; host `test_w008.c`, ours
  `test_w008_tracks_relayed_peer_identity`). **Open (→ T06b):** how that health bit
  gates into the Modbus WarningCode is not yet pinned (it does not surface in the bare
  harness). Decisions recorded in [`docs/31`](31-factory-quirks.md).
