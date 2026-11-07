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
- **Status:** confirmed. **Test (T11c):** the factory reproduces it in
  [`test_arm_sim_factory_only.py`](../tests/test_arm_sim_factory_only.py)
  `test_bms_frame_misfiling_quirks_q1_q2` (IR 101 = 7700); ours does not
  ([`test_arm_sim_self_only.py`](../tests/test_arm_sim_self_only.py)
  `test_bms_frame_misfiling_quirks_not_reproduced`, IR 101 = 0).

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
- **Status:** confirmed. **Test (T11c):** same pair as Q1 —
  `test_bms_frame_misfiling_quirks_q1_q2` asserts the factory's IR 97 = 0x4E50
  (20048) while IR 96 module count is correct; `..._not_reproduced` asserts ours
  leaves IR 97 = 0 and still publishes IR 96.

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
- **Status:** confirmed (for this image / `P07-LUX` preset). **Test (T11c):** the
  factory side [`test_arm_sim_factory_only.py`](../tests/test_arm_sim_factory_only.py)
  `test_bms_alarm_b_reaches_no_register_q3` (inject only 0x35A → no IR 81-106 moves);
  ours [`test_arm_sim_self_only.py`](../tests/test_arm_sim_self_only.py)
  `test_bms_alarm_b_not_decoded`.

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
- **Status:** suspected. **Test (T11c):** no new test — this is a unit-label
  question, not a value bug. The **1:1 pass-through** both images perform (IR 98 =
  raw 0x356 current) is already locked for both by
  [`test_arm_sim.py`](../tests/test_arm_sim.py)
  `test_can_battery_telemetry_reaches_modbus`. Which physical unit is correct
  (0.01 A vs 0.1 A) stays open pending a live-bus reading; no scale is asserted.

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
  (`tests/settings_contract.py`, image `ceaa-07xx_vE_260214.bin`). Static isolation of the
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
  `65`, not a `900-5000` voltage. So on `ceaa-07xx_vE_260214.bin` HR 22 behaves as an
  **unimplemented / remapped** address, not the documented PV-start-voltage.
- **Expected:** a documented, writable holding register.
- **Evidence:** fresh-boot dongle write/read probe (`tests/settings_contract.py`).
  Could be variant/image-specific (probed on the committed ceaa-07xx image; the
  register may live elsewhere or be gated on another revision).
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

## Q10 — the DSP's `0x49` telemetry is built but not received by the ARM on USART3

- **Area:** ARM↔DSP link (`docs/wiring/ARM-USART3-DSP/telemetry-0x49.md`, T09)
- **Observed:** the DSP builds a `0x49` ('I') type-1 telemetry frame and writes it
  to its SCI-B TXBUF (builder `FUN_0009DD14` → `FUN_0009D358`), the return wire of
  the ARM→DSP config push. But the ARM's **USART3 RX** (ISR `sub_0801c774` → drain
  `sub_0801c6e0` → byte handler `sub_0801c3e6`, buffer `0x20007490`) is a
  Modbus-slave + bootloader **demux**: it accepts only func `03/04/06/10` and
  `21/22/23` after an address match, and **resets the assembler on anything else**,
  so a `0x49`/type-1 frame never assembles. The ARM's own `0x49` telemetry is the
  **safety CPU's** frame on **USART2** (`cmp #0x49` in `sub_0801c808`, parser over
  buffer `0x20009048`), a different ISR entirely.
- **Expectation:** the symmetric "config out / telemetry back on the same wire"
  reading (earlier `telemetry-0x49.md`) implied the ARM parses the DSP's `0x49`
  on USART3. It does not.
- **Evidence:** App vector table + `tools/disres.py` on `ceaa-07xx_vE_260214.bin`
  (`sub_0801c3e6` dispatch; `sub_0801c808` SOF test); dynamic oracle
  `tests/test_dsp_rx.py` (the real byte handler drops a `0x49` SOF, assembles
  Modbus/bootloader). Static + dynamic.
- **Interpretation:** either the DSP's SCI-B `0x49` is not wired to USART3 RX in
  hardware, or it is delivered and silently dropped. Either way it is not an ARM
  telemetry source; the ARM relies on the USART2 safety-CPU telemetry.
- **Our firmware:** faithfully reimplements the USART3 RX as the demux
  (`inv_dsp_rx_classify`, `src/dsp/dsp_rx.c`); it does not attempt to parse a
  `0x49` on USART3. No behavioural change needed — this is a corrected
  understanding, not a bug to fix.
- **Verdict:** replicate (the demux is the real behaviour); the "DSP 0x49 on
  SCI-B goes nowhere on the ARM" leg is **still-to-decide** pending a hardware
  schematic / capture of the SCI-B return line.

---

## Not quirks (recorded so we don't re-flag them)

These surprised us at first but are defensible factory behaviour; our firmware
matches them deliberately:

- **`0x356` voltage → IR 4 is rounded**, not truncated (0.01 V → 0.1 V,
  round-half-up: `5325` → `533`). We round to match.
- **`0x351` charge-voltage limit → IR 83 is clamped** to a cell-count-derived
  maximum (~57.4 V on this pack) before publishing. Reasonable safety behaviour;
  we currently publish the pack's value as-is and test below the clamp.

---

## OSS behaviour decisions — identity & command registers (T12)

Not factory quirks; these are **our** firmware's chosen behaviour for the
identity/command registers (docs/39 T12), recorded so they are deliberate:

- **W008 (FW-version mismatch) — RESOLVED to a model-IDENTITY compare (T02b).** The
  earlier T12 note ("leave W008 clear until a remote DSP *version* is received")
  was based on the wrong model. Once the USART2 wire ran (T02), the real mechanism
  was pinned ([`HR009_010`](wiring/ARM-UART5-dongle/HR009_010-FW-versions.md)): the
  classifier (`sub_0801a93a`) case-insensitively compares the **peer identity** the
  safety CPU relays (tag-0 frame `+0x15..+0x18` → bank `+3..6`) against the model
  code **"ceaa"**, setting the "version-OK" health bit `0x2000d890` **bit 10** only
  on a match. Proven both directions on the factory (match → bit 10 set, mismatch →
  clear; `test_usart2_identity_drives_version_health_bit`). **Ours implements this**
  (`src/safety/safety_cpu.c`, `inv_fw_ident_matches` vs `inv_variant()->model_code`):
  W008 (`INV_LOCAL_WARN_W008`) is raised while the relayed identity has not matched
  and **latched** clear once it does — mirroring the factory's latched health bit (a
  later mismatch does not re-raise it; the peer identity is constant per boot, so the
  latch is never observable mid-run). **Open (T06b-adjacent):** in the bare harness
  the health bit does not surface as a WarningCode bit at `STATE+0x9c`, so the factory's
  gating of that bit into the Modbus WarningCode is unconfirmed; ours surfaces W008 in
  the WarningCode per spec (`WARN_FW_VERSION_MISMATCH`), which may differ from the
  factory in states where it suppresses the warning.
- **HR 9/10 versions.** Ours reports its own build versions as read-back
  (`OSS_ARM_COMMS_VER` → HR 9 high, `OSS_FW_VERSION_CODE` → HR 10 high; HR 9 low =
  0 redundant CPU). **HR 10 low (DSP version) is now live**: refreshed each loop from
  the relayed safety-bank byte `bank+2`, proven to reach HR 10 over Modbus on the
  factory (`test_usart2_dsp_version_reaches_hr10_low`). Read-only — a write draws
  exception (T04).
- **Request-SN checking (HR 2-6).** Ours runs with **`check_sn = false`**: it does
  **not** reject a dongle frame whose 10-byte SN differs from ours; the SN is
  echoed, not matched. Rationale: maximise interop with monitoring tools that do
  not know the unit's SN. (What the *factory* replies to a wrong SN — silence vs
  an exception — is **not observable in this harness**: the factory answers the
  harness on USART3 (`ModbusDsp`), while the request-SN check, if any, sits on the
  **dongle UART5** slave task, which the sim does not schedule — a separate
  factory-dongle harness, **not** the T02 USART2 work, which is done. The factory's
  provisioned SN in the sim is also not its real one. Open; see HR002_006-SN.)
- **HR 11 ResetSetting is one-shot.** Ours applies each set bit as an action and
  reads the register back as 0 (never stored) — `src/state/command.c`,
  dispatching: bit 0 → clear energy/runtime counters, bit 7 → `SCB->AIRCR`
  SYSRESETREQ reboot (the factory's mechanism, confirmed in the 07 image:
  `0xE000ED0C`/`0x05FA0004` present; docs/23), bits 5/6 → BMS charge/discharge
  switch requests. Bits 1/2/3/4 (defaults / adj-ratio / fault & monitor records)
  are **accepted and ignored for now** — the defaults field-table and record
  stores are docs/23 open items — rather than faked.
- **HR 15 ComAddr timing.** Ours adopts the new slave address **after** the write's
  own reply has been sent (the write is ACKed on the old address, the next request
  uses the new one) and persists it (T03), re-adopting it at boot. No reboot
  needed. (Whether the *factory* switches on the same reply or after a reboot is
  the UART5-path question above — not observable here.)

## Q11 — the factory's HR write-validation surface differs from the spec (and ours under-validates)

- **Area:** holding-register writes (docs/04, docs/23). Found by the whole-HR
  boundary sweep (docs/39 **T24**, [`test_wrsem_sweep.py`](../tests/test_wrsem_sweep.py)
  / [`wrsem_contract.py`](../tests/wrsem_contract.py)): every ranged HR probed at
  `min-1 / min / max / max+1` on a fresh boot, factory verdict recorded in
  [`wrsem_expected.py`](../tests/wrsem_expected.py). 103 vectors → 39 accept,
  43 `reject:3` (ILLEGAL_VALUE, out of range), 19 `reject:2` (ILLEGAL_ADDRESS —
  **not writable**), 2 `reject:4` (SLAVE_FAILURE — read-only).
- **Not writable at all (`reject:2`, any value):** HR 22 (StartPVVolt — was Q7),
  **67** (ACChgSocLimit), **74/82/83** (charge-priority / forced-discharge power+SOC
  — the registers already shown inert for the DSP push, `INERT_64_89`), and **145**
  (OutputPrioConfig). A write is rejected regardless of value.
- **Tighter than the documented range:** HR **20** and **59** max is **6**, not the
  doc's 7 (7 is `reject:3`); HR **23** rejects its documented max 600; HR **24**
  rejects both 0 and 900; HR **105** rejects 10 (min is higher than the doc's 10);
  HR **112** rejects value **2** (slave — Q9) while 0/1/3 are taken; HR **113**,
  **144**, **146** reject every probed value in the bare-boot state.
- **One-sided bounds (confirms Q6):** HR **75 / 99 / 101 / 105** accept above their
  documented max but reject below min. HR **9 / 10** are read-only (`reject:4`).
- **Read-only ends:** HR 9/10 (versions) reject every write with exception 4.
- **Our firmware (after T24b):** `settings_validate` now enforces the factory's
  per-register bounds — the tighter maxes (HR 20/59 = 6), the shifted/one-sided
  bounds (HR 75/99/100/105/196), the not-writable set (HR 22/67/74/82/83/145 →
  exception 2) and HR 112's value-2 reject. The sweep's 58 deviations collapse to
  **11**, all on the three registers the factory rejects for *every* value in the
  bare-boot state — **HR 24** (ReconnectTime), **HR 113** (SetComposedPhase),
  **HR 144** (FloatChargeVolt). Those are left permissive on purpose (they are
  almost certainly precondition-gated — no value is accepted even in range — so
  blocking valid writes would be wrong); recorded in `wrsem_expected.OURS_DEVIATIONS`,
  which `test_wrsem_sweep.py` guards against growth.
- **Caveat — verdicts are the cold-boot state.** Each probe is a fresh boot with no
  operating mode set, so registers the factory gates on a precondition (a running
  state, a mode, standby-only writes) show as `reject` here; that is the inverter's
  state at probe time, not proof the register is permanently unwritable. The
  `reject:2` set is stable across boots; the `reject:3`-for-all cases (HR 113/144/146)
  are the ones most likely to be precondition-gated — flagged for T24b.
- **Status:** confirmed (ceaa-07xx, black-box, cold-boot). Oracle committed; ours
  parity gap recorded.
