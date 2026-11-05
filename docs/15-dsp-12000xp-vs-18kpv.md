# DSP firmware: 12000XP vs 18kPV — commonalities & differences

A side-by-side of the two TI C28x **control-DSP** images, to see how much of the
DSP reverse-engineering (docs/05–10) carries across EG4 models. This is the
**DSP-side** counterpart to [`docs/10-18kpv-vs-12000xp.md`](10-18kpv-vs-12000xp.md),
which compares the two **ARM "com" MCU** images.

- **12000XP:** `…CEAA-xx07_dsp_vE_250325` — 141,304-byte image (this is the DSP
  all of docs/05–10 analyses).
- **18kPV:** `…fAAB-xx22_Para375_20250428` — 269,888-byte image (~1.9× larger).

Both were decoded the same way (Ghidra 12.1.2 + `ghidra-tms320c28x`): convert the
vendor `.hex`, **byte-swap** to on-chip word order, import at flash word base
`0x80000`, run the headerless pipeline. The figures below are from that pass;
they describe what each *firmware* does, not the board.

## At a glance

| | 12000XP | 18kPV |
|---|---|---|
| Image size (bytes present) | 141,304 | **269,888 (~1.9×)** |
| Flash span (words) | `0x80000`–`0x9FFFD` | `0x80000`–`0xA21A0` (+`0xBFF00`) |
| Functions recovered | 651 | 450 (fewer, much larger) |
| Largest function (words) | 2,169 | **4,730** (several > 3,200) |
| SCI serial ports used | mainly **SCI‑B** (+trivial A) | **SCI‑A + SCI‑B + SCI‑C** |
| ePWM register refs | 786 | 1,273 |
| Inter-proc comms handler | `FUN_00080AA8` @`0x80AA8` | `FUN_00080534` @`0x80534` |
| Output-priority var(s) | `0xADA8` | `0x154A` **and** `0x154D` |
| Config blob base | `0x00AC80` | (different; not `0xAC80`) |
| Word-for-word identity at same address | — | **4.9%** (0.5% non-`0xFFFF`), longest run 8 words |

## Commonalities — same codebase family, same ARM↔DSP contract

1. **Same silicon class.** Both are **TI C28x / F2837x-class** (flash word-base
   `0x80000`; ePWM, 4× ADC, CLA peripherals labelled on both).
2. **Same vendor image format.** Intel HEX with byte addresses = 2× the C28x
   word address, and **byte-swapped** (each 16-bit word stored high-byte-first).
   Both needed the identical swap to decode — `LCR` opcode counts jump
   6→1422 (12kXP) and 10→1498 (18kPV) after swapping.
3. **Same image structure.** A **sector-0 flash bootloader/updater** plus a larger
   application region; same flash-sector gap pattern.
4. **Same ARM link = SCI‑B.** SCI‑B is the primary inter-processor serial port in
   both (12kXP 29 refs, 18kPV 39).
5. **Same tagged extended command family.** Both sector-0 comms loops
   (`FUN_00080AA8` ↔ `FUN_00080534`) dispatch off the frame's function byte and
   handle the extended codes **`0x21`/`0x22`/`0x23`** (the firmware-update /
   tagged command set). The exact framing of the *runtime config* path (a
   separate message type on the same SCI-B link) is covered in
   [`docs/05`](05-dsp-link.md)/[`docs/08`](08-arm-dsp-config-protocol.md) and is
   under active cross-checking between the DSP and ARM sides — this comparison
   only asserts that **both DSP images carry the same `0x21/0x22/0x23` handler**,
   which they do.
6. **Same "AC First" concept.** An output/charge-priority value tested **`== 2`
   (AC First)**, gated by **bit 3 of a grid-charge-enable flags word**:
   - 12kXP: `DAT_0000ADA8 == 2 && (DAT_0000AD84 & 8) == 8` (see [`docs/07`](07-dsp-ac-first-mode.md))
   - 18kPV: `(DAT_0000154D == 2 || DAT_0000154A == 2) || (DAT_00001551 & 8) == 8`
7. **I2C‑A parked, not used.** Both init the I2C‑A frame once and issue no master
   transactions — no I2C storage/RTC on either (see [`docs/09`](09-dsp-persistence-and-clock.md)).
8. **ePWM-based power control** in both.

## Differences

1. **Separate builds, different memory maps.** Only **4.9%** of words are
   identical at the same flash address (0.5% ignoring `0xFFFF` fill), longest
   identical run just 8 words. This is **not** one binary patched into the other —
   every config/RAM address differs. The 12kXP's config blob `0xAC80` and
   output-priority `0xADA8` **do not appear** in the 18kPV; its analogs live near
   `0x154x`. So the DSP RAM layout must be re-derived per image.
2. **Bigger and more complex.** The 18kPV image is ~1.9× larger and its control
   functions are 2–3× bigger (top 4,730 vs 2,169 words). Consistent with the
   18kPV being the fuller hybrid — the README notes the 12000XP is the non-hybrid,
   2-MPPT **subset** of the 18kPV-12LV **superset**.
3. **More serial peers.** The 18kPV drives **three** SCI ports (A/B/C); the
   12kXP essentially only SCI‑B. The 18kPV has extra links (candidates:
   parallel/phase, meter, or BMS on dedicated ports — unconfirmed).
4. **Richer AC-First gating.** The 18kPV combines **two** priority variables
   (`0x154A`, `0x154D`) with `||` plus the enable, versus the 12kXP's single
   variable with `&&`. Suggests the 18kPV separates charge-vs-output priority, or
   handles more sources/phases.
5. **Slightly larger frame header.** The comms function-code byte sits at buffer
   offset `0x1B7` (18kPV) vs `0x1B3` (12kXP) — a ~4-byte-larger header.
6. **CRC implementation differs.** The 12kXP computes CRC‑16/Modbus with the
   inline bitwise polynomial constant **`0xA001`** (2 sites). The 18kPV image has
   **no `0xA001`/`0x8005`/`0x1021` immediate** — most likely a **table-driven
   CRC** (same CRC‑16 result, different code). *Not yet confirmed by reading the
   routine.*
7. **More PWM.** 1,273 vs 786 ePWM references — a larger / more-complex power
   stage on the 18kPV.

## Interpretation

Same vendor codebase lineage and the **same ARM↔DSP contract** — SCI‑B link, the
`0x21/0x22/0x23` extended protocol, and the AC-First output-priority +
grid-charge-enable gating — recompiled for different hardware with a different
memory map and an expanded feature/port set. The 18kPV is the bigger sibling.

**Practical consequence for the port:** the *shape* of the DSP-side work
(docs/05–10) carries over to the 18kPV — same protocol, same concepts — but every
concrete artefact that is an address (the config blob base, the per-field offsets
of [`docs/10-dsp-config-field-map.md`](10-dsp-config-field-map.md), the output-priority variable, the
`b300`-style completeness mask) must be **re-derived against the 18kPV image**;
none of the 12kXP addresses transfer.

## Confidence & open items

- **High confidence:** sizes, byte-swap, F2837x class, sector-0 comms handler,
  SCI-B link, `0x21/0x22/0x23` protocol presence, AC-First `==2 + enable-bit`
  gating in both, and the low same-address identity (separate builds).
- **Unconfirmed:** the 18kPV's CRC being table-driven (inferred from the absence
  of the `0xA001` immediate, not yet read); what the extra SCI‑A/SCI‑C links talk
  to; and the exact semantics of the two 18kPV priority variables. These need a
  focused 18kPV decode pass (the equivalent of docs/07–10) if the project targets
  that model.
- Figures (ref counts, function sizes) are from one automated recovery pass; the
  18kPV recovered fewer functions (450) partly because more of its larger image is
  data/control tables and some code may remain unseeded.
