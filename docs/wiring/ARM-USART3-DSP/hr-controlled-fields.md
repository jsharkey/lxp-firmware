# HR-controlled DSP fields — end-to-end confidence (both factory images)

> Which DSP RAM fields a **dongle Modbus holding register** ultimately controls —
> directly (e.g. charge voltage) or indirectly (e.g. a schedule the ARM evaluates
> against its RTC) — with a single confidence rating per field, justified by
> **agreement across both factory images**. See the [index](fields.md),
> [field-provenance](field-provenance.md) (ARM struct→block), and
> [`docs/10`](../../10-dsp-config-field-map.md) (block→DSP target).

## Method — the Rosetta stone is agreement at both ends

Each chain is `dongle HR → ARM settings/working struct → ARM block builder →
DSP block offset → DSP RAM target → DSP consumer`. A field's confidence is high
only when independent evidence from **both** images lines up *and* the engineering
**unit** is consistent end to end:

- **ARM factory image** `ceaa-07xx_vE_260214` (522 KB, App@`0x08005000`): the real
  per-block builder `sub_08024dfc` emulated field-by-field (field-provenance), the
  register getter `fn_ceaa` (`0x08032000`), and — new here — per-register **dongle
  writability** probed live under Unicorn (`tools/arm_sim.py` + `tests/arm_sim_modbus.py`).
- **DSP factory image(s)** `…07_dsp` (12kXP) / `…22_Para375` (18kPV): the consumer
  that *reads* each target, which fixes the unit/semantics (`tools/` C28x dump).
- **Register semantics / scaling**: [`include/inv/modbus_map.h`](../../../include/inv/modbus_map.h).

**Confidence legend:** **proven** = both ends pinned and units agree ·
**high** = one end pinned, other strongly corroborated by unit match ·
**medium** = role clear, exact HR↔field not individually pinned ·
**low** = plausible guess.

## Honest limitation of the live-capture path

The differential capture method (write a dongle HR, rebuild the block, diff bytes —
`tests/dsppush_contract.py`) only moves bytes for fields the builder reads
**directly** from the canonical settings struct. For this image a bare dongle
write does **not** propagate to the block even after pumping the main loop: the
`HR-shadow → settings-struct → slot/limit working-struct` sync needs an
apply/mode event a lone `write_single` doesn't trigger (verified: writes read back
via `fn_ceaa` but no struct/block byte moves). So the ARM→block half rests on
**static builder emulation** (field-provenance), not a live diff; the live run is
retained for the **writability** facts below, which it does establish cleanly.

---

## 1. Direct scalar settings — **proven**

| HR | name (unit) | ARM path | block·off | DSP target | DSP consumer / meaning | conf |
|---|---|---|---|---|---|---|
| **145** | `OUTPUT_PRIO_CFG` (0 Bat / 1 PV / 2 AC-First) | `HR145 → 0x2000a343 → ` | **0 · `0x1E`** | `0xADA8` | FSM tests `==2` ⇒ AC First (docs/07) | **proven** |
| **20** | `PV_INPUT_MODEL` (0-7) | canonical `0x2000986c` | **0 · `0x28`** | `0xAD8D` | PV routing/parallel select | **proven** |

Both: the **enum/range matches exactly** at both ends (the only `{Bat,PV,AC-First}`
enum in the system is HR145, and the DSP's only `==2` mode test is `0xADA8`; HR20's
0-7 range and name validated by offset). Dongle-writable on the factory image
(HR145 ✓, HR20 ✓).

## 2. Grid-charge / AC-First schedule windows — **proven** (times pushed; verdict ARM-only)

The window **times** are HR-controlled and reach the DSP; the **"window active
now" verdict is computed on the ARM against its RTC and is *not* pushed** — the
indirect/calendar-based case.

| HR group | name | ARM path (committer → slot) | block·off | DSP target | conf |
|---|---|---|---|---|---|
| **68–73** | AC-charge windows (3× start/end) | `sub_08022fde`/`…3044` → slot `0x2000a370–a37a` | **4 · `0x17…0x21`** | records `0xADB5/B6/B7…` (`FUN_0009CCBD/CD03`) | **proven** |
| **152–157** | AC-First windows (3× start/end) | `sub_080230b6`/`…3128` → slot `0x2000a37c–a386` | **5 · `0x17…0x21`** | records `0xADBB/BC/BD…` (`FUN_0009CD49/C7EE`) | **proven** |

- Packing matches both ends: `low = hour(0-23)`, `high = minute(0-59)`
  (`modbus_map.h`, field-provenance). The DSP stores these as **opaque type-coded
  records** (change-detect → AC-First-gated enqueue → dispatch), never comparing
  them to a clock — [`clock.md`](clock.md).
- **RTC verdict stays ARM-side:** `sub_080352d0` walks the AC-First windows,
  `start ≤ now < end` (midnight-wrap) → **IR 126 bit 8** (`IR_ACFIRST_WIN_ACTIVE`),
  not pushed ([HR152-157](../../wiring/ARM-UART5-dongle/HR152_157-ACFirst-windows.md), docs/25).
- Writability (factory image): HR 68–73 store once AC-charge is enabled; HR 152–157
  did **not** store in the default state (feature-gated — AC-First must be enabled
  first), consistent with the committer's feature-enable gate. HR 67 / 74–89
  (AC-charge SOC, charge-priority, forced-discharge) are inert in this image, so
  there is nothing to push (dsppush_contract).

## 3. Battery charge/discharge limits (block 1) — **indirect**, BMS+compute-derived

The DSP's limit calculator `FUN_0009520C` takes the **min** of the ARM-pushed set
(`0xB234–B23B`) and the live BMS set (`0xB22C–B233`), producing the charge-voltage
target (`0xB222`/`0xB243`) and current limits (`0xB245…B24B`). The ARM pushes block
1 from the **battery-limits working struct** `0x2000a68c…a69f`, *computed* from BMS
**+** settings (field-provenance writers `sub_0800adc8`/`db42`/`1ddc0`). So the DSP
value is a **resolved limit**, not a raw register copy — the user's "indirect"
case.

| DSP field | DSP-side unit (consumer) | plausible HR input(s) | conf |
|---|---|---|---|
| `0xB237` (→target `0xB222`/`B243`) | **charge voltage**, 0.1 V (clamp floor 48.0 V; ×10 → 0.01 V, 48.00–60.00 V) | HR 99 `CHARGE_VOLT_REF` / 144 `FLOAT_CHARGE_VOLT` / 148 `BAT_NOMINAL_VOLT` (all **0.1 V**) | role **high**, exact HR **low-med** |
| `0xB239` (→`0xB229`) | **charge current limit**, 0.1 A (min'd vs `0xADA4`) | HR 101 `CHARGE_CURR` (A), min'd with BMS | role **high**, exact HR **medium** |
| `0xB23A` (→`0xB22A`) | **discharge current limit**, 0.1 A (min'd vs `0xADA6`) | HR 102 `DISCHG_CURR` (A), min'd with BMS | role **high**, exact HR **medium** |
| `0xB236` | **flags/enable word** (bit `0x100` = limits valid/enable) | HR 21 `FUNC_EN` / BMS presence | **medium** |

**Unit cross-check (the confidence lever):** the DSP interprets block-1 voltages in
**0.1 V** and currents in **0.1 A**, and the candidate HRs are documented in exactly
those units (voltages 0.1 V; currents A → 0.1 A after the ARM's ×10) — the ends
agree on *kind and scale*, which is why the **block identity is high** even though
the compute step blocks a 1:1 HR↔field pin. Dongle-writable on the factory image
(in-range): HR 99 ✓, 101 ✓, 102 ✓, 144 ✓, 147 ✓, 148 ✓; HR 100 `CUT_VOLT_DISCHG`
did not store in the default state (discharge-control-mode gated).

## 4. AC-charge enable bit — **medium**

The DSP gates grid charging on `0xADA8==2 && (0xAD84 & 0x08)` (docs/07). `0xAD84`
is block 0 `0x1B`, sourced ARM-side from the derived slot-record `0x2000a332`; the
enable ultimately traces to the **AC-charge** bit of HR 21 `FUNC_EN` (and/or HR 120
`SYS_ENABLE`), but through the slot computation rather than a direct copy — hence
**medium**.

---

## Out of scope — not HR-controlled

Blocks **2, 7, 8** are **measurement calibration gains** (Q10, unity `0x400`),
sourced from an ARM ext-settings region **not served by `fn_ceaa`** — i.e. **no
dongle read/holding register exposes them** (factory trims), so they are not
HR-controlled. See [`block-02`](block-02.md)/[`block-07`](block-07.md)/[`block-08`](block-08.md).

## Factory-image writability (new, reliable)

Probed live on `ceaa-07xx_vE_260214` (dongle write of an in-range value, then
read-back). "stored" = the write took; "gated" = did not store in the default
state (needs a feature/mode enabled first or an out-of-mode value), **not** proof
of read-only.

| stored | HR 20, 21, 23, 24, 64–66, 68–73*, 99, 101, 102, 110, 120, 144, 145, 147, 148 |
|---|---|
| **gated / inert** | HR 67, 74–89, 100, 152–157* (*windows store only once their feature is enabled) |

> Reproduce: `LXP_FACTORY_BIN=<flat.bin> python3 tests/test_dsp_push.py` (writability
> test), or the probe in this doc's commit message. The proprietary image stays out
> of the repo.
