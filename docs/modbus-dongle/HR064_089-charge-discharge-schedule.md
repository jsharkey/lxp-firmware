# HR 64-89 — charge/discharge schedule

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

Three parallel features, each = **PowerCMD % + SOCLimit % + three time windows**
(each window = start/end, packed `low=hour(0-23)`, `high=minute(0-59)`):

| feature | power | SOC | windows (start/end ×3) |
|---|---|---|---|
| AC-charge | 66 | 67 | 68-69, 70-71, 72-73 |
| Charge-priority | 74 | 75 | 76-77, 78-79, 80-81 |
| Forced-discharge | 82 | 83 | 84-85, 86-87, 88-89 |

(HR 64/65 are the general Charge/DischgPowerPercentCMD.)

## Side-effects of writing

**Persisted to config flash; the schedule is evaluated ARM-side against the
clock.** The time windows are checked against the RTC the ARM owns (the same
`hour|minute` packing as the AC-First windows). The ARM decides *when* a window is
active; it does **not** push the per-window verdict as a separate signal
([`docs/25`](../25-modbus-register-spaces.md) establishes this pattern for the
AC-First window). Higher-resolution `0.1%` power variants live at HR 138-143.

## Where these reach the Control DSP (ARM→USART3 config push)

Traced register-exact through the ARM config builder in `ceaa-07xx_vE_260214.bin` — full chain
in [`docs/modbus-dsp/field-provenance.md`](../modbus-dsp/field-provenance.md):

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
