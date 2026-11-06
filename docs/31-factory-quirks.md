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

- **Area:** battery CAN → Modbus (`docs/20`, `docs/wiring/ARM-UART5-dongle/IR081_106-BMS.md`)
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

- **Area:** dongle Modbus / scheduler (`docs/25`, `docs/wiring/ARM-UART5-dongle/HR126_131-OptimalChg_DisChg.md`)
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
  evaluate time windows anyway ([`docs/wiring/ARM-USART3-DSP/clock.md`](wiring/ARM-USART3-DSP/clock.md)).
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

---

## Q6 — holding-register range checks enforce only one bound on some registers

- **Area:** dongle Modbus write validation (`docs/39` T04,
  `docs/wiring/ARM-UART5-dongle/HR099_102-leadacid-charge.md`, `HR105-EOD.md`)
- **Observed:** a holding-register write is range-checked, and an out-of-range
  value is **rejected** (Modbus exception `3` ILLEGAL_VALUE, value not stored —
  confirmed for HR 15/20/66, which reject above their max). But a few registers
  enforce only the **lower** bound:
  - **HR 101 `ChargeCurr`** (spec `0-140`): a write of `141` is **accepted and
    stored** (echo), and the cold default reads `250` — both above the spec max.
  - **HR 105 `EOD`** (spec `10-90`): `9` is rejected (exc 3), but `91` is
    **accepted and stored**. Lower bound enforced, upper bound not.
- **Expected:** the published ranges are two-sided; a value above the max should
  be rejected (or clamped) like one below the min.
- **Evidence:** fresh-boot-per-value dongle write probe (the harness RX state
  degrades after a rejected write, so each value is probed on a fresh boot),
  classifying the reply (echo vs exception + code) and the read-back
  (`tests/settings_contract.py`, image `com_flat.bin`). Static isolation of the
  per-register validator was not achieved (the symbol map's regeneration merged
  it), so this is a dynamic finding.
- **Our firmware:** **replicated for parity** — `settings_validate()`
  (`src/settings/settings_validate.c`) uses `NO_MAX` for HR 101/105 so the common
  test (`tests/test_settings_validate.py`) is green on both images. A stricter OSS
  validation enforcing the documented upper bound is a reasonable **fix
  candidate** — still-to-decide; flip the table entry and the vector if we take it.
- **Status:** confirmed (for this image).

## Q7 — HR 22 `StartPVVolt` is not writable on this image (exception 2)

- **Area:** dongle Modbus write validation (`docs/wiring/ARM-UART5-dongle/HR022-StartPVVolt.md`)
- **Observed:** a func-`0x06` write to **HR 22** (documented `StartPVVolt`,
  `900-5000`) returns **exception `2` (ILLEGAL_ADDRESS)** regardless of the value
  (tried in-range `2500` and out-of-range `899`), and a read of HR 22 returns
  `65`, not a `900-5000` voltage. So on `com_flat.bin` HR 22 behaves as an
  **unimplemented / remapped** address, not the documented PV-start-voltage.
- **Expected:** a documented, writable holding register.
- **Evidence:** fresh-boot dongle write/read probe (`tests/settings_contract.py`).
  Could be variant/image-specific (this is the ceaa 05-family image; the register
  may live elsewhere or be gated).
- **Our firmware:** ours implements HR 22 in its register map, so ours would
  **accept** an in-range write where the factory rejects it — a deliberate
  divergence, **not** asserted in the common write-semantics test. Needs more RE
  (is HR 22 remapped, or write-gated behind a mode?) before we match or fix.
- **Status:** suspected (one image, func-06 only; func-16 and other images untried).

## Q8 — HR 21 (`FuncEn`) does not read back verbatim; the factory OR-s a capability bit

- **Area:** dongle Modbus settings (`docs/23`, `docs/wiring/ARM-UART5-dongle/`)
- **Observed:** write `FuncEn = 0x0136` (310) over the dongle and read it back and
  the factory returns `0x0336` (822) — the stored value **OR-ed with `0x200`**
  (bit 9). The stored record byte is exactly what was written (`+0x13` in slot 0);
  only the *read* is a merge.
- **Interpretation:** `FuncEn` is a bitmask and the factory reports it with a
  firmware-forced capability/enable bit set regardless of what was stored, so the
  Modbus read reflects the *effective* mask, not the stored one. Not a storage bug
  — a read-side merge.
- **Our firmware:** stores and reads `FuncEn` verbatim (no forced bit), so a
  straight write/read round-trips. The cross-image persistence oracle therefore
  checks `(got & written) == written` for HR 21 (our bits must all survive) rather
  than exact equality (`tests/test_persist_crossimage.py`, `READ_OR_MASK`).
- **How found:** the full-table cross-image round-trip (task T03): every other
  pinned register read back verbatim; HR 21 came back with the extra bit.
- **Status:** confirmed (ceaa-07xx). Which bit-9 function it advertises is not yet
  named.

## Q9 — HR 112 (`SetSystemType`) rejects value 2 (slave) in a black-box write

- **Area:** dongle Modbus settings (`docs/23`)
- **Observed:** a dongle `0x06` write of `SetSystemType = 2` (1-ph parallel
  **slave**) draws **no echo** — the factory rejects it — while `= 1` (master) is
  accepted and stored (`+0x1b`, slot 0). The register is otherwise writable.
- **Interpretation:** selecting slave is gated on a parallel-system precondition
  (a master/phase/ID must be configured first), so a bare write is refused. This
  is the same "gated write" class docs/23 notes for ~47 other registers.
- **Our firmware:** has no such validation yet (accepts any value); range/precondition
  checks are task T04. The persistence oracle writes `= 1` (the accepted value).
- **How found:** nudging the T03 test value to 2 drew no echo; 1 round-tripped.
- **Status:** confirmed (ceaa-07xx, black-box). The exact precondition is unpinned.

---

## Not quirks (recorded so we don't re-flag them)

These surprised us at first but are defensible factory behaviour; our firmware
matches them deliberately:

- **`0x356` voltage → IR 4 is rounded**, not truncated (0.01 V → 0.1 V,
  round-half-up: `5325` → `533`). We round to match.
- **`0x351` charge-voltage limit → IR 83 is clamped** to a cell-count-derived
  maximum (~57.4 V on this pack) before publishing. Reasonable safety behaviour;
  we currently publish the pack's value as-is and test below the clamp.
