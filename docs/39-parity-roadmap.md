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

To claim a task, edit its **Status** line to
`[~] <agent/handle> <YYYY-MM-DD>`, commit it on its own
(`docs/39: claim T07`), and push **before** you start the real work. If the
rebase shows someone else claimed it first, pick another task.

When you finish, set the line to `[x]`, link the commits/docs/tests, and tick
the matching README Status box if there is one.

If a task turns out bigger than its card, split it: add `T07a`, `T07b` under it
rather than renumbering. Other agents reference these IDs.

Several tasks touch `src/main.c`, so keep your edits there small. Each task
should land its logic in its **own module** (`src/<area>/…`) and add only a
call/wiring line or two to `main.c`. Rebase often.

---

## Where we stand (gap snapshot)

| area | factory | ours today | gap |
|---|---|---|---|
| Dongle Modbus port | UART5 + RS-485 DE ([`wiring/ARM-UART5-dongle`](wiring/ARM-UART5-dongle/README.md)) | engine bound to **USART3** (`src/modbus/modbus_port.c`), the same port as the DSP push (`src/dsp/dsp_link_port.c`) | **blocks real hardware**; harness `ModbusDongle` also drives USART3 |
| Settings persistence | 56 HRs pinned in slots 0/5 ([`docs/23`](23-arm-config-writer.md)) | **2** persisted (HR 101/102, `settings_persist_hr` in `src/main.c`) | 54 registers |
| Write validation | factory getters/setters range-check (unverified) | `/* TODO: validate ranges */` in `mb_wr_hold` | unknown, needs oracle |
| Safety-CPU USART2 | wire frame → bank → IR ([`docs/33`](33-usart2-telemetry-bank.md)) | bank → IR only (`src/safety/safety_cpu.c`). **No USART2 driver or parser**; tests poke `g_safety_bank` | RX parser, IR 0 / 6 / 60-63 not published |
| State / fault classifier | `sub_0801b480` ([`docs/22`](22-arm-dsp-core-split.md)) | `IR_STATE` hard-seeded to Standby in `main.c` | whole classifier |
| ARM-computed telemetry | powers, RunningTime, etc. ([`docs/22`](22-arm-dsp-core-split.md), [`ARM-UART5-dongle`](wiring/ARM-UART5-dongle/registers.md)) | energy integrator only (`src/energy/`) | IR 7-11, 16-17, 24-27, 69-70, … |
| DSP link RX | `0x49` telemetry parsed by `FUN_08025ab8` ([`wiring/ARM-USART3-DSP/telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md)) | **TX only** | parser + link-loss supervision |
| DSP config push | 9 blocks fully populated | block 0 partial, blocks 4/5 (slots) done, **1-3, 6-8 empty** (`src/dsp/dsp_config.c`) | 6 block payloads |
| BMS / CAN | RX decode, limit derivation, keep-alive, `0x35A` | RX decode for 0x351/355/356/359 (`src/can/bms_can.c`). Keep-alive payload is "provisional" | limits → DSP, TX payload, quirks Q1-Q4 |
| Command registers | HR 11 reset / defaults / reboot, HR 15 addr, SN | HR 15 seeded once; `check_sn=false`; HR 11 inert | command semantics |
| Schedules | AC-First + AC-charge windows evaluated ARM-side | AC-First window verdict only (`src/sched/acfirst.c`); optchg is dormant in the factory too (Q5) | charge/discharge/gen schedules + SOC/V gates |
| Relays | driven by the mode task `sub_0801b3dc` ([`docs/18`](18-power-path-relays.md)) | `src/relay.c` mirrors 2 contracts | sequencing under the live mode |
| HMI | full menu + editors | menu engine on the real panel (`src/hmi/`) | **status dashboard** (editors out of scope) |
| Harness depth | — | factory RTOS tasks **don't run** in the sim, so peer data is injected at the bank, not on the wire ([`docs/19`](19-gpio-test-harness.md), `tests/arm_sim_safety.py`) | wire-level e2e for USART2/USART3/relay task |

Register-level coverage: **28 of 55** `docs/wiring/ARM-UART5-dongle/` register files list **no
test** at all (recount as of T04). These include IR 6, 10-11, 16-17, 19, 26-27,
60-63, 69-70, 77, 107 and HR 11, 16, 23-62, 103, 110, 112-113, 146-148, 194-198.
(T04 added write-validation coverage for HR 9-10, 15, 20, 22, 66, 101, 105.) The
tasks below are what close them.

---

## P0 — unblockers and the biggest gaps

### T01 — Move the dongle Modbus slave to UART5 (ours + harness)
**Status:** `[~] claude/019chjb 2026-11-06` · **Layer:** sim (common) · **Unblocks:** T08, all hardware use

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

### T02 — Run the factory's RTOS tasks in the simulator
**Status:** `[~] claude-opus/019chjbE 2026-11-06` · **Layer:** harness (`tools/arm_sim.py`) · **Unblocks:** T05, T08, T14, wire-level e2e

The factory's mode/relay loop (`sub_0801b3dc`) and the USART2 frame task
(`sub_080259d8`) are **PendSV-switched RTOS tasks** that never get the CPU in
the harness ([`docs/19`](19-gpio-test-harness.md) §"The factory runs a
preemptive RTOS"). So today we inject peer data **at the bank** and call the
relay drive code directly. Make the first SysTick→PendSV launch work: find what
the task-create path waits on (config-flash contents? DSP-link handshake?), seed
it, and confirm a task runs.
- **Done when:** a factory sim test can (a) feed **raw USART2 bytes** and see IR
  values change, and (b) change the operating state and see PC6 move, **without
  calling an internal function**. Document the recipe in docs/19. A boot
  snapshot cache that keeps this fast is part of the job (see the boot-cache
  pattern in [`docs/28`](28-factory-hmi.md)).
- Note: this is pure harness work. It changes no firmware, so it can run fully
  in parallel with T03/T04.

### T03 — Persist the full pinned settings table (54 more registers)
**Status:** `[~] claude 2026-11-06` · **Layer:** sim (cross-image) + host · **Independent**

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
**Status:** `[x] claude 2026-11-06` · **Layer:** micro (per-register vectors) + one sim smoke · **Independent**

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

---

## P1 — the live data path (telemetry, state, faults)

### T05 — USART2 safety-CPU receiver: wire frame → bank
**Status:** `[ ]` · **Layer:** host (parser) + sim (wire e2e, needs T02) · **Depends:** T02 for the factory e2e half

We have the bank → IR half (`src/safety/safety_cpu.c`), but **nothing fills the
bank from the wire**. The frame (SOF `0x49`, type-1, big-endian, tag
sub-records, CRC-16) is laid out in [`docs/33`](33-usart2-telemetry-bank.md) §1
and [`wiring/ARM-USART2-safety`](wiring/ARM-USART2-safety.md).
- **Ours first is OK here.** A host-tested parser (`src/safety/safety_rx.c`)
  with frames built from the docs/33 layout: good CRC, bad CRC, truncated,
  unknown tag, resync after garbage. Add a USART2 driver (RS-485, check docs/16
  for the DE pin). The factory uses DMA; we need not.
- **Oracle:** once T02 lands, a common sim test feeds the **same raw bytes** to
  both images and compares the served IRs. Until then, the existing bank-level
  common test is the oracle for the serve half.
- Record `rx-timeout → fault` behaviour for T08.

### T06 — Operating-state classifier + fault/warning composer (`sub_0801b480`)
**Status:** `[ ]` · **Layer:** **micro** (classic case) + sim e2e · **Unblocks:** T13, T14

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
**Status:** `[ ]` · **Layer:** micro (scaling/rounding) + sim · **Independent** (sources may be injected)

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

### T08 — Peer-link supervision: comms-loss faults, timeouts, recovery
**Status:** `[ ]` · **Layer:** **micro (timeout boundaries)** + sim · **Depends:** T05/T09 for the wires; T06 for where the bits land

What happens when the DSP, safety CPU or BMS goes quiet? Expect E000/E017/E018/
E031 "internal communication fault" bits, a BMS-loss warning, and probably a
state change and relay drop. **Prove it:**
- **Oracle:** stop feeding each peer in the factory sim and find the exact
  timeout: last frame at `t`, fault **not** set at `T-1`, set at `T`. Then
  check **recovery**: does the fault clear on the first good frame, or after N,
  and is it latched until reset? For each peer this gives one boundary
  micro-test plus one e2e test.
- **Ours:** a small `link_watchdog` module (pure: `last_rx_tick, now → ok/lost`)
  per peer, wired into T06's local-flags input.

### T09 — DSP link RX: parse the `0x49` telemetry frame
**Status:** `[ ]` · **Layer:** host + sim · **Independent** (factory RX path `FUN_0801bb0e`/`FUN_08025ab8`)

Our link is TX-only. The factory parses DSP `0x49` frames on USART3
([`wiring/ARM-USART3-DSP/telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md)). The authoritative
state and faults come from USART2 (docs/22), so first **find out what the ARM
actually consumes from `0x49`**: link-alive, DSP version, the block
acknowledge/completeness mask?
- **Oracle:** inject `0x49` frames into the factory over USART3 and diff the
  RAM/IR changes (`tools/ramxref.py`, `tools/emu_regrange.py`).
- **Ours:** an RX ring on USART3 (the ISR already exists in `src/uart/uart3.c`)
  and a block parser that mirrors `dsp_build_config_frame`.
- Record the findings in `docs/wiring/ARM-USART3-DSP/telemetry-0x49.md`.

### T10 — Fill the DSP config-push payloads (blocks 1, 2, 3, 6, 7, 8 + rest of 0)
**Status:** `[ ]` · **Layer:** sim (byte-exact frame diff) · **Independent** (per-block, parallelisable: one agent per block is fine)

Block meanings are recovered ([`wiring/ARM-USART3-DSP/`](wiring/ARM-USART3-DSP/fields.md):
1 = battery limits, 2/7/8 = calibration gains, 3/6 = grid-charge slots), but
`dsp_config.c` sends them **empty**. `tests/test_dsp_push.py` already captures
the factory's frames off USART3, so extend it:
- **Oracle:** for each block, capture the factory frame under ≥3 different
  settings snapshots and assert each field's byte position/width/endianness
  tracks the source HR or struct field ([`wiring/ARM-USART3-DSP/field-provenance`](wiring/ARM-USART3-DSP/field-provenance.md)).
- **Ours:** fill the field tables. Block 1 depends on the BMS-limit struct
  (T11), and the cal-gain blocks need a source for the gains (factory config
  slot? record it).
- **Done when:** our USART3 frames are **byte-identical** to the factory's for
  the same settings + BMS state, and the CRC byte order question
  (`DSP_CRC_MSB_FIRST`) is settled by capture.

### T11 — BMS: charge/discharge limit derivation + inverter→BMS TX
**Status:** `[ ]` · **Layer:** micro (clamp math) + sim (CAN e2e) · **Independent**

- **Limits.** The factory derives a working charge-V / charge-I / discharge-I
  from **BMS 0x351 + settings** (HR 99-102, 147-148, EOD 105) into the struct
  that block 1 pushes. Note that it already clamps the charge voltage to a
  cell-count max of about 57.4 V (comment in `main.c` `on_can_frame`). Oracle
  the derivation as a micro-test: BMS limit vs. setting vs. clamp, with the
  boundary at each crossover. Publish the IR 81-106 values it feeds.
- **TX.** Our keep-alive `0x305`-class frame sends **zeros** ("payload
  provisional", docs/20). Capture the factory's CAN TX (ids, period, payload
  under different states) in the sim and match it. Some BMS presets need this
  to keep the pack's contactor closed.
- **Alarms / quirks.** Decide [`docs/31`](31-factory-quirks.md) **Q1-Q4**
  (`0x355` SOC → max-cell-V, `0x359` "PN" → capacity, `0x35A` dropped, IR 98
  10× unit). Each verdict is either a factory-green test we copy or an explicit
  "fixed in ours" test, plus a docs/31 entry.
- Covers the IR 81-106 gaps in the docs/wiring/ARM-UART5-dongle coverage list.

---

## P2 — features and commands

### T12 — Identity and command registers: HR 11, HR 15, SN (HR 2-6), FW versions (HR 9-10)
**Status:** `[ ]` · **Layer:** sim · **Depends:** T03 (persistence of addr / SN)

- **HR 11 ResetSetting** ([`HR011`](wiring/ARM-UART5-dongle/HR011-ResetSetting.md),
  [`docs/23`](23-arm-config-writer.md) §Reset-to-default): find out what each
  bit does in the factory sim (clear energy records? defaults → which slots get
  rewritten, to what? reboot → when? BMS switch?). Assert the post-state.
- **HR 15 ComAddr:** after a write, does the slave answer on the new address
  **immediately** or after reboot? Is address 0 broadcast?
- **SN (HR 2-6):** how is it set (`0x10` only?), how is it persisted, and is
  the request SN **checked** (our `check_sn=false`)? What does the factory reply
  to a wrong SN: silence or an exception?
- **HR 9-10 versions + W008:** we report our own version, and W008 comes from
  the version compare ([`HR009_010`](wiring/ARM-UART5-dongle/HR009_010-FW-versions.md)).
  Decide in docs/31 what ours does on a version mismatch.

### T13 — HMI status dashboard (overview screen; no editors)
**Status:** `[ ]` · **Layer:** sim (panel framebuffer) + host (layout) · **Soft-depends:** T06/T07 for real values (works with injected values earlier)

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
**Status:** `[ ]` · **Layer:** sim · **Depends:** T02 (relay task runs), T06 (real state)

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

### T15 — Charge/discharge schedules with SOC/voltage gates (HR 64-89, 158-169)
**Status:** `[ ]` · **Layer:** **micro (window × SOC × V boundaries)** + sim · **Independent**

We evaluate only the **AC-First** window (`src/sched/acfirst.c`). The AC-charge
window evaluator has a factory-vs-ours micro-test already
(`tests/test_timewindow.py` `test_acchg_*`). Still missing:
- **Forced-discharge** and **charge-priority** windows (HR 74-89) through the
  same `timewindow_contract.py` profile mechanism.
- The **SOC/voltage gates** that start/stop AC charge (HR 64-67 power/SOC
  limits, HR 158-161 ACChg-by-V/SOC, HR 160s bat-low/OngridEOD,
  HR 120 ACChargeType selecting time vs SOC vs V). Sweep with **hysteresis
  boundaries**: start at X, stop at Y, and what happens between.
- Where the verdict lands: IR status bits? Pushed to the DSP? Check the block 0
  / slot fields.
- HR 126-131 OptimalChg is **dormant in the factory** (docs/31 Q5). Don't
  implement it beyond the existing round-trip unless that verdict changes.

### T16 — Generator: charge start/stop, quick start, warm-up/cool-down (HR 194-198 + 07-series)
**Status:** `[ ]` · **Layer:** micro (thresholds/timers) + sim · **Soft-depends:** T14 (gen relay)

[`HR194_198`](wiring/ARM-UART5-dongle/HR194_198-generator-charge.md) start/end V/SOC and
max gen charge current, plus the 07-series additions
([`docs/11`](11-12000xp-revisions.md) #1 gen charge time scheduling, #2 quick
start 20-min cycle, #3 warm-up/cool-down, #15 no gen charge while Smart Load is
active). First locate the backing registers/settings for the 07-only features
(they may be outside the published spec). Write them up in `docs/wiring/ARM-UART5-dongle/`,
then oracle the start/stop thresholds and timers at their boundaries.

### T17 — Remaining 07-series features: Smart Load, Resume SOC, Quick Charge, buzzer
**Status:** `[ ]` · **Layer:** RE + micro + sim · **Independent**

From [`docs/11`](11-12000xp-revisions.md): #6 Quick Charge (start, system
charge SOC/V limit), #7 discharge-resume threshold (+5 % / +2 V hysteresis,
which is a natural micro-test), #9 battery warning buzzer (find the GPIO via
[`docs/16`](16-arm-io-map.md)), #11 Smart Load power display (Psmart / Peps_port /
Pgrid_side: which IRs?). One agent can take each feature. Each needs the
register/setting located, a factory oracle, then ours.

---

## P3 — later / lower leverage

### T18 — Firmware-update pass-through (`0x21/0x22/0x23`, State = Programming)
**Status:** `[ ]` · Layer: sim. The ARM relays DSP firmware updates
([`wiring/ARM-USART3-DSP/bootloader-21_23`](wiring/ARM-USART3-DSP/bootloader-21_23.md)) and reports
IR 0 = `0x02`. Needed eventually so that field updates of the DSP keep working
under our firmware. Our own ARM update path (the bootloader layout in docs/11)
is a separate, later question.

### T19 — Grid self-test (AutoTest, HR 98 / IR 71-75), parallel systems (HR 112-114, IR 113), AFCI (IR 140-152)
**Status:** `[ ]` · Mostly hybrid/region-specific and likely inactive on a
standalone 12000XP. First **prove whether each one is live on `ceaa-07xx`**
(the getter returns constants? a setter with no effect?), then record "dormant"
the way HR 126-131 was handled (`92d8e49`). Implement only what is live.

### T20 — Variant parity (18kPV `FAAB`, 6000XP `ccaa`)
**Status:** `[ ]` · Re-run the oracle suites against the other App images
(hash table in `README.md`) once the 12000XP suites are broad. That needs the
per-image `PROFILES` approach of `timewindow_contract.py` generalised across
tests. Note: `lxp-factory` currently holds only the `ceaa-07xx` ARM image.

### T21 — Hardware bring-up checklist
**Status:** `[ ]` · Once T01/T03/T05 land, write the bench procedure: flash
layout vs the 07 bootloader (vectors at `0x08005000`, docs/11; our 12000XP
link script is still monolithic at `0x08000000`, so decide which), panel init,
RS-485 DE, CAN bitrate. Also cover how to recover a unit that bricks.

---

## Cross-cutting, always-on

- **Coverage bookkeeping:** every task above that touches a register updates
  that register's `## Test coverage`. The "26 of 54 files list no test" figure
  in the gap snapshot should go **down** with every task. Recount it when you
  close one.
- **Harness speed:** sim tests get slower as they grow. Any agent that adds a
  sim test should reuse the warm-once / clone-per-case pattern
  ([`docs/19`](19-gpio-test-harness.md) §"Warm once, clone per case") and
  prefer a micro-test for boundary sweeps.
- **Quirks:** add each new docs/31 entry *as soon as you see it*, even while
  your task is still in flight.

## Dependency sketch

```
T01 UART5 ─────────────┐
T02 RTOS tasks in sim ─┼─> T05 USART2 RX ─┐
                       │   T09 DSP RX ────┼─> T08 link supervision ─┐
                       │                  │                         ├─> T13 dashboard (real data)
T06 classifier ────────┼──────────────────┴─────────────────────────┤
                       └─> T14 relays (needs T02 + T06) ─> T16 gen  │
T03 persistence ─> T12 identity/commands                            │
T04 validation   (independent)                                      │
T07 computed IRs (independent) ─────────────────────────────────────┘
T10 DSP blocks  <── T11 BMS limits (block 1)
T15 schedules, T17 07-series features   (independent)
```

Tasks that start **today with no dependency**: T01, T02, T03, T04, T06 (micro
half), T07, T09, T10 (blocks 2/3/6/7/8), T11, T13 (with injected values), T15,
T17.
