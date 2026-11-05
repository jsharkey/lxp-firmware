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
- **Likely cause:** a field/offset mix-up in the `0x355` handler (the high-res
  SOC word is routed to the cell-voltage slot), or the max-cell-voltage source
  frame was never wired up and this slot was reused.
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

---

## Not quirks (recorded so we don't re-flag them)

These surprised us at first but are defensible factory behaviour; our firmware
matches them deliberately:

- **`0x356` voltage → IR 4 is rounded**, not truncated (0.01 V → 0.1 V,
  round-half-up: `5325` → `533`). We round to match.
- **`0x351` charge-voltage limit → IR 83 is clamped** to a cell-count-derived
  maximum (~57.4 V on this pack) before publishing. Reasonable safety behaviour;
  we currently publish the pack's value as-is and test below the clamp.
