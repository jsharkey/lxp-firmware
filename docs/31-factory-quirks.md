# Factory firmware quirks & bugs

A running catalogue of **unexpected behaviours** found in the factory (stock)
firmware images while reverse-engineering and building the harness — things that
deviate from the published protocol (the EG4 Modbus doc, the standard "CAN bus
battery" family) or from plain common sense.

Why track them separately:

- When our open-source firmware must match the factory as an oracle (the common
  harness tests, `docs/19`), a quirk is a decision point: **replicate** it (to
  stay bug-compatible with existing tooling) or **fix** it (and accept the test
  divergence). Each entry records which we chose and why.
- Some are genuine bugs worth reporting upstream; others are harmless oddities
  or preset-specific behaviour. Either way, writing them down keeps us from
  "rediscovering" the same surprise later.

Most are found empirically: inject a known input through the harness
(`tests/arm_sim_can.py`, `tests/arm_sim_modbus.py`), run the factory image, and
read back what it produced — see each entry's *How found*.

**Status legend:** `confirmed` (reproduced), `suspected` (one observation),
`fixed-upstream` (vendor addressed it in a later build).

---

## Q1 — `0x355` high-res SOC lands in the max-cell-voltage register

- **Area:** battery CAN → Modbus (`docs/20`)
- **Observed:** CAN frame `0x355` byte `[4:5]` (high-resolution SOC, ×0.01 %) is
  copied into Modbus input register **101 `MaxCellVolt_BMS`** (0.001 V). With
  SOC = 77 % the register reads `7700` — i.e. a **7.7 V cell**, which is
  physically impossible for LFP.
- **Expected:** `MaxCellVolt_BMS` should carry the pack's maximum cell voltage
  (a per-cell measurement, ~3.2–3.6 V → `3200`–`3600`). The high-res SOC belongs
  with the other SOC fields, not in a cell-voltage register.
- **Root cause (confirmed):** the real max-cell-voltage source — the extended
  cell frame **`0x373`** (min/max cell voltage & temperature) — is **never wired
  to IR 101** on this image. Injecting `0x373` with realistic values changes no
  register, and the whole extended `0x370–0x381` / `0x311–0x321` range is received
  but published to no register at all (the inverter aggregates to one logical
  pack — see [`docs/34`](34-multi-battery-can.md)). With that slot left unfed, the
  `0x355` high-res SOC word bleeds into it instead of the cell voltage. So it is
  the "source frame never wired up, slot reused by a field/offset mix-up" case,
  not a simple typo in an otherwise-correct handler.
- **Our firmware:** does **not** reproduce it — we leave IR 101 alone rather than
  publish a bogus cell voltage. So the common telemetry test does not assert
  IR 101.
- **How found:** `CanBattery.send_soc_soh(77, 96)` then read IR 101 off the
  factory image → `7700` (= SOC×100). Baseline (no frame) reads `0`.
- **Status:** confirmed.

## Q2 — the `0x359` `"PN"` marker lands in the battery-capacity register

- **Area:** battery CAN → Modbus (`docs/20`)
- **Observed:** CAN frame `0x359` carries a fixed two-byte ASCII marker `"PN"`
  at byte `[5:6]` (standard "CAN bus battery" layout). The factory stores those
  bytes into Modbus input register **97 `BatCapacity`** (Ah): it reads `0x4E50`
  = **20048 Ah**.
- **Expected:** `BatCapacity` should be the pack capacity in Ah (tens to low
  hundreds). The `"PN"` bytes are a frame marker, not data, and should not be
  stored as capacity.
- **Our firmware:** does not reproduce it (we do not publish IR 97 from CAN).
- **How found:** inject `0x359` with bytes `… 'P' 'N' …`; read IR 97 off the
  factory → `0x4E50`. (The adjacent byte `[4]` = module count → IR 96
  `BatParallelNum` is handled correctly, so this is specifically the marker.)
- **Status:** confirmed.

## Q3 — `0x35A` alarms are received but never surface on Modbus

- **Area:** battery CAN → Modbus (`docs/20`)
- **Observed:** CAN frame `0x35A` (the second protection/alarm set) is received
  and staged in RAM, but its contents reach **no** Modbus input register. A full
  sweep of all 160 input registers shows zero change when only `0x35A` is
  injected — whereas `0x359` populates the fault/warn registers (IR 99/100) as
  expected.
- **Expected:** if `0x35A` is part of the active alarm contract, its bits should
  surface somewhere readable (e.g. the fault/warning bitfields). Either it is
  unused in the `P07-LUX` preset (then receiving/staging it is dead work) or a
  publish step is missing.
- **Our firmware:** consumes `0x359` only; `0x35A` is intentionally not decoded
  (would be unpublished dead code). Noted so a future contract change is a
  deliberate choice, not an oversight.
- **How found:** inject only `0x35A` with distinctive words; read all input
  registers (groups 0-39/40-79/80-119/120-159) off the factory → no change.
  Confirmed the bytes *are* in RAM (staging), so it is received, not dropped.
- **Status:** confirmed (for this image / `P07-LUX` preset).

## Q4 — `0x356` battery current may reach IR 98 with a 10× unit mismatch

- **Area:** battery CAN → Modbus (`docs/20`, `docs/modbus-dongle/IR081_106-BMS.md`)
- **Observed:** the dongle Modbus spec calls IR 98 `BatCurrent_BMS` **0.01 A**
  (and IR 81/82 max charge/discharge current likewise 0.01 A), but the
  battery-firmware frame map ([`include/inv/bms_can_map.h`](../include/inv/bms_can_map.h),
  a byte-exact read of the pack's `0x356` builder) records the current field as
  **0.1 A**. Both firmwares forward the raw `0x356` value to IR 98 **1:1** (ours
  in `src/main.c`; the factory, per the `test_can_battery_telemetry_reaches_modbus`
  assertion that `IR 98 == raw`). If the map's 0.1 A unit is right, every current
  the dongle reads is then **10× low** against the register's declared 0.01 A.
- **Expected:** one consistent unit end to end — the pack's wire unit and the
  register's declared unit agree, or the inverter rescales between them.
- **Unresolved:** we have not confirmed which label is right. The two dongle-side
  sources (the EG4 Modbus PDF and the IR doc) agree on 0.01 A; the lone 0.1 A is
  the RE-derived battery-map note, which could itself be mislabeled. Resolving it
  needs a live-bus reading (a known pack current vs the register) or a deeper read
  of the pack's current getter. Until then neither physical unit is asserted in
  tests — the BMS tests check the integer passes through 1:1, not its scale.
- **Our firmware:** matches the factory (1:1 forward); no rescale added pending
  the resolution above.
- **How found:** cross-checking the Modbus PDF (IR 98 = 0.01 A) against
  `bms_can_map.h` (0x356 current = 0.1 A) while sweeping the BMS block.
- **Status:** suspected.

## Q5 — `OptimalChg_DisChg` (HR 126-131) is defined but never evaluated

- **Area:** dongle Modbus / scheduler (`docs/25`, `docs/modbus-dongle/HR126_131-OptimalChg_DisChg.md`)
- **Observed:** the 48-slot × 2-bit half-hour charge/discharge table is fully
  writable and reads back (stored at RAM `0x2000D814`, next to the RTC), and the
  spec gates it behind `stSysEnable.HalfHourACChrStartEn` (HR 120 bit 0). But the
  ceaa-07xx image **never acts on it**: nothing compares the current half-hour
  slot against the clock, nothing drives charge/discharge from a slot mark.
- **Expected:** with the gate enabled, the current slot's mark (1 charge /
  2 discharge) should influence behaviour — as the spec's "charge and discharge
  mark" wording implies.
- **Root cause (confirmed dormant):** the only code touching the `0x2000D814`
  block is the config clear/init (`sub_080147ac`), the Modbus **getter**
  (`sub_0801d48c`, `0x03` read path) and **setter** (`sub_0801f596`, `0x06`/`0x10`
  write path). No evaluator reads it. A `UC_HOOK_MEM_READ` over the block sees
  zero reads during a long run except when a dongle `0x03` of HR 126-131 runs the
  getter. Writing the table moves no DSP config-push byte, and the DSP does not
  evaluate time windows anyway ([`docs/modbus-dsp/clock.md`](modbus-dsp/clock.md)).
  So the feature is present in the register map but inert in this firmware — the
  same "defined but dormant" pattern as the per-pack range (IR 5000-5126).
- **Our firmware:** keeps a tested pure evaluator (`optchg_slot_mode()`,
  `tests/test_optchg.c`) but deliberately does **not** wire it into the loop, to
  stay behaviour-compatible with the dormant factory. The only shared black-box
  contract is the store/read-back round-trip
  (`test_modbus_optchg_table_roundtrip`).
- **How found:** writing HR 126-131 over the dongle (writable, reads back),
  then a full-RAM and DSP-config differential across an in-slot vs out-of-slot
  clock sweep (gate on) — nothing moved — plus static tracing of every
  `0x2000D814` reference and a runtime read-hook.
- **Status:** confirmed (for this image; a later image could wire it up).

## Q6 — the dongle read path ignores the 40-register group rule

- **Area:** dongle Modbus read (`0x03/0x04`) (`docs/38`, `docs/04`, `docs/25`)
- **Observed:** the EG4 spec says a query spans **≤ 40 registers** and must not
  cross a 40-register group boundary (`0-39`, `40-79`, …); a violation should
  return exception `0x02`. The `ceaa-07xx` read path (`sub_0801ef68`) enforces
  **neither**. It serves 41 registers from `start 0`, serves `start 39, count 2`
  (which straddles the 39/40 boundary), and serves up to **127** registers in
  one response. The only limits are a hard **count ≥ 128 → exception** and a
  func-`0x03` guard that rejects `start+count` in `[0x0FFF, 0x1388)`.
- **Expected:** per the published rule, >40 or a boundary-crossing read → `0x02`.
- **Evidence (confirmed):** static read of the count check in `sub_0801ef68`
  (`cmp #0x80`, no 40-group test) plus dynamic injection against the factory
  image — `read_holding(0,41)`, `read_holding(39,2)`, `read_holding(0,127)` all
  return data; `read_holding(0,128)` returns an exception
  ([`docs/38`](38-dongle-modbus-crash-surface.md)).
- **Our firmware:** **diverges deliberately** — `query_span_ok()` enforces the
  ≤40 + no-boundary-cross rule and returns exception `0x02`
  ([`docs/04`](04-modbus.md)). A monitoring tool written to the factory's
  leniency (one >40 read) would get a `0x02` from us. Decision point: keep the
  stricter spec-correct behaviour (current) or relax to match the factory.
- **Status:** confirmed. Not a crash — a response-shape/compat deviation.

## Q7 — a truncated frame transiently deafens the register channel

- **Area:** dongle Modbus frame assembler (`docs/38`)
- **Observed:** the frame assembler (`sub_0801b6be`, struct `@0x2000a304`) holds
  a partial frame by position until its declared length arrives. If a frame is
  cut off after a **valid** function byte (so the length is already latched) and
  the bus then goes quiet, the **next** frame's bytes append onto the stale
  prefix instead of starting fresh → that frame fails CRC and is lost. A stream
  of partial frames can keep the channel unresponsive.
- **Expected:** a clean RTU slave resyncs on the inter-frame gap (t3.5), so a
  truncated frame costs at most itself.
- **Evidence (confirmed, self-healing):** the processor `sub_0802d9b2`
  increments a stall counter `[@0x2000a304+0x456]` each comms-task cycle it runs
  without a complete frame and, at **10** cycles, resets the assembler
  (`[+0x44e]/[+0x452]/[+0x458] = 0`) — a software stand-in for the gap flush.
  Dynamically: `truncated-half-frame → valid-read` fails to answer across a short
  idle but **recovers** once the idle gap is long enough for the flush to fire
  (~10 cycles) ([`docs/38`](38-dongle-modbus-crash-surface.md)). Garbage and
  bad-CRC floods recover immediately (an invalid function byte resyncs at once).
- **Our firmware:** the transport layer should resync on the RTU inter-frame
  gap so a partial frame never consumes the next one; verify our `modbus_port.c`
  gap handling does this (it is framing-timeout based, not a 10-cycle counter).
  No crash either way — an availability quirk, worst case a self-healing channel
  stall under a sustained partial-frame flood.
- **Status:** confirmed (transient; self-heals on an idle gap).

## Q8 — HR 11 / HR 15 are dongle-reachable disruption commands (by design, but note them)

- **Area:** dongle Modbus write (`0x06`) (`docs/38`,
  `docs/modbus-dongle/HR011-ResetSetting.md`, `docs/modbus-dongle/HR015-ComAddr.md`)
- **Observed:** these are not bugs but they are the *only* way a frame on this
  bus visibly disrupts the inverter, so they are recorded here deliberately.
  **HR 11** is a command bitfield a single `0x06` write triggers — bit 7
  `InvReboot` (restart), bit 1 `AlltoDefault` (wipe settings to default + persist
  to flash), bits 5/6 the BMS charge/discharge switches. **HR 15** moves the
  inverter's own Modbus slave address; after the write it answers only on the new
  address, orphaning a master that keeps polling the old one.
- **Evidence:** dynamic — every HR 11 bit (incl. 7 and 1) echoes and the ARM
  **stays alive** in the RTOS emulation (the reboot did not manifest as a crash
  in-emu); HR 15 ← 2 then reads on addr 1 stop and reads on addr 2 answer
  ([`docs/38`](38-dongle-modbus-crash-surface.md)).
- **Our firmware:** treat HR 11/HR 15 as privileged commands behind an explicit
  writable-register allow-list; don't expose a bare "any holding register is
  writable" surface. A reboot/defaults/address-change command should be gated
  (and ideally rate-limited), not a reflexive side-effect of a register write.
- **Status:** confirmed (intended behaviour; logged as a remote-disruption
  surface, not a firmware defect).

---

## Not quirks (recorded so we don't re-flag them)

These surprised us at first but are defensible factory behaviour; our firmware
matches them deliberately:

- **`0x356` voltage → IR 4 is rounded**, not truncated (0.01 V → 0.1 V,
  round-half-up: `5325` → `533`). We round to match.
- **`0x351` charge-voltage limit → IR 83 is clamped** to a cell-count-derived
  maximum (~57.4 V on this pack) before publishing. Reasonable safety behaviour;
  we currently publish the pack's value as-is and test below the clamp.
