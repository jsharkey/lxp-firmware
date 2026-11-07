# HR 64-89 — charge/discharge schedule

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

Three parallel features, each = **PowerCMD % + SOCLimit % + three time windows**
(each window = start/end, packed `low=hour(0-23)`, `high=minute(0-59)`):

| feature | power | SOC | windows (start/end ×3) |
|---|---|---|---|
| AC-charge | 66 | 67 | 68-69, 70-71, 72-73 |
| Charge-priority | 74 | 75 | 76-77, 78-79, 80-81 |
| Forced-discharge | 82 | 83 | 84-85, 86-87, 88-89 |

(HR 64/65 are the general Charge/DischgPowerPercentCMD.)

## Side-effects of writing

**Persisted to config flash.** The three features' "active now" verdicts are
computed ARM-side by one combined evaluator (`sub_0801ed28`, decoded on the
**05-series** image; the committed 07 image's AC-charge window evaluator is
`0x08034590`), landing in three bytes **`0x2000aa5f/60/61`** (05-image addresses;
AC-charge / charge-priority / forced-discharge), gated by a master-enable + the
HR 120 mode bits + the window +
SOC/limit/status — see [`docs/41`](../../41-charge-discharge-schedule-gates.md).
**Note the division of labour:** for **AC-charge**, the ARM **pushes the window
times to the DSP** (config block 4, see below) and the DSP time-gates them; the ARM
verdict byte `0xaa5f` in isolation reflects the feature-enable, not the window.
Contrast **AC-First** (HR 152-157), which the ARM evaluates itself and surfaces at
IR 126 bit 8 ([`docs/25`](../../25-modbus-register-spaces.md)). Higher-resolution
`0.1%` power variants live at HR 138-143.

## Where these reach the Control DSP (ARM→USART3 config push)

Traced register-exact through the ARM config builder in `ceaa-07xx_vE_260214.bin` — full chain
in [`docs/wiring/ARM-USART3-DSP/field-provenance.md`](../../wiring/ARM-USART3-DSP/field-provenance.md):

| field | pushed to DSP? | path |
|---|---|---|
| **AC-charge windows** HR 68/69/70/71/72/73 | **yes** | → slot-committers `sub_08022fde`/`sub_08023044` → slot records `0x2000a370…a37a` → **DSP config block 4 `0x17…0x21`** |
| AC-charge **power/SOC** HR 66/67 | **unresolved** | not in the `fn_ceaa` settings struct; no committer reads it (static trace blind) |
| **Charge-priority** HR 74–81 | **unresolved** | whole feature absent from the settings struct / committer reads |
| **Forced-discharge** HR 82–89 | **unresolved** | whole feature absent from the settings struct / committer reads |

So it is the ARM that **pushes** the AC-charge window times into the per-block
snapshot (not a DSP "pull"), gated by the feature-enable bits in `0x2000a7a4`. The
parallel **AC-First** windows (HR 152–157) reach **block 5 `0x17…0x21`** the same way.
"Unresolved" means the static method cannot see it (register-indexed storage outside
the canonical struct) — **not** that it is confirmed absent; a live USART3 capture
would settle it.

## On the LCD (EG4 12000XP manual)

SETTINGS → **Charge tab**: `AC Chg Based On` selects the AC-charge mode (**default Disable**; options: According to Time / Bat Voltage / Bat SOC / Battery Volt and Time / Battery SOC and Time), exposing up to **3 AC-charge windows** (P1-P3 Start/End, 00:00-23:59) plus `AC Charge Battery Current` (**default 30A**) and voltage/SOC start-end thresholds. (The charge-priority / forced-discharge blocks are the schedule analogues.)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Writability + DSP push (HR 64-73):** [`test_dsp_push.py`](../../../tests/test_dsp_push.py) / [`dsppush_contract.py`](../../../tests/dsppush_contract.py) — `WRITABLE_64_89`/`INERT_64_89` pin which registers store, and `DSP_PUSH` pins that HR 68-73 (AC-charge windows) push to config block 4 while HR 66 (power) is stored but not pushed.
- **AC-charge windows vs RTC (HR 68-73):** [`test_timewindow.py`](../../../tests/test_timewindow.py) / [`timewindow_contract.py`](../../../tests/timewindow_contract.py) `acchg` — the factory evaluator profile (`0x08034590`) runs on the committed `ceaa-07xx_vE_260214.bin`, where these tests **pass** (`test_acchg_factory_*`); they skip cleanly on images that lack it, e.g. the older 05-series image (see [`docs/41`](../../41-charge-discharge-schedule-gates.md), [`docs/39`](../../39-parity-roadmap.md) T15).
- **HR 67 + HR 74-89:** contract-asserted **inert** in the factory image (a dongle write does not store) — see `INERT_64_89`.
- **Write validation (HR 66, T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `50` accepted, `101` (> max 100) rejected with Modbus exception 3 (not clamped, not stored); host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
