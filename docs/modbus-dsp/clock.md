# Clock frame — ARM real-time clock stream (the DSP does **not** consume it)

> **ARM-built**, a *third* framing seen on this wire family (not a type-1 block,
> not the bootloader). Unsolicited, streamed continuously. See the
> [index](README.md).
>
> **Headline (proven from the DSP image):** the Control DSP does **not** parse
> this frame, keeps **no** wall clock, and does **no** time-of-day arithmetic. So
> whatever the ARM streams, the DSP does **not** use it to evaluate AC-First /
> AC-charge time windows. The window "active now?" decision is the **ARM's**
> ([HR152-157](../modbus-dongle/HR152_157-ACFirst-windows.md), docs/25, docs/36).

## The frame (ARM-side)

```
preamble : 0xA5 0xA5
payload  : year, month, day, hour, minute, second   (the ARM's RTC)
```

- Source buffer: ARM RAM `0x20009754`; builder `sub_08021df8` *(ARM-side
  provenance; not re-verified against the current 07-series image here)*.
- Sent **unsolicited** (unlike the config blocks, which are a continuous full
  snapshot the DSP diffs).
- **Caveat on destination.** That the ARM *builds* a `0xA5A5` clock frame does not
  establish that it reaches the **Control DSP**: the DSP image has no matching
  parser (below), so if the frame is emitted on SCI-B the DSP drops it, and it may
  in fact be aimed at a different peer (meter/logger/dongle). Pinning its actual
  wire is an **ARM-side** follow-up.

## What the DSP does with the RTC value — nothing (proven)

A full scan of both Control-DSP images (12kXP `…07_dsp_vE_250325`, 450–651
recovered functions; 18kPV `…22_Para375_20250428`) finds **no clock consumer**:

- **No preamble match.** There is no `0xA5` / `0xA5A5` / `165` immediate anywhere
  in either image — neither in the decompilation nor in the raw disassembly
  listing. The DSP's SCI-B receiver only dispatches **`0x41`** (type-1 config) and
  **`0x21`/`0x22`/`0x23`** (bootloader); its other framed links are the safety-CPU
  **`'T'`/`'D'`** (`0x54`/`0x44`, SCI-C, docs/29) and the MPPT `0x42` (docs/13).
  A `0xA5`-prefixed frame matches none of these.
- **No wall-clock variable.** Consistent with [`docs/09`](../09-dsp-persistence-and-clock.md):
  no RTC peripheral, no SPI/I²C RTC, timers free-running (not dated). Nothing in
  RAM is loaded with a `y/m/d/h/m/s` calendar.
- **No time-of-day arithmetic.** The scan finds **none** of the operations a
  window evaluator must have — no `hour*60+min`, no `%60` / `/60` / `*60`, no
  compares against `24`/`60`/`1440`/`23`/`59`/`12`/`31`. (The one `*600` in the
  18kPV image is a float power/thermal divisor under the TMU, not time.)

A device that evaluated "is the current time inside `[start,end]`?" would need
exactly this arithmetic against a current-time value. Both are categorically
absent, so the DSP **cannot** be doing window evaluation.

## What the DSP does with the pushed start/end window times — store, diff, queue by code (proven)

The raw `hour|minute` window times **are** pushed to the DSP (they ride in the
full config snapshot): AC-charge windows → **block 4** `0x17…0x21`, AC-First
windows → **block 5** `0x17…0x21`
([field map](../10-dsp-config-field-map.md), [HR152-157](../modbus-dongle/HR152_157-ACFirst-windows.md)).
On the DSP they are treated as **opaque, type-coded parameter records**, never as
clock-compares:

| stage | function(s) | what happens |
|---|---|---|
| deserialise / stage stored copy | `FUN_00092EE2`, `FUN_00092110` | unpack block 4/5 payloads into record RAM (block 4 → `0xADB5/B6/B7`, block 5 → `0xADBB/BC/BD`, …) |
| commit per record | `FUN_0009CCBD` (blk4), `FUN_0009CD49` (blk5), … (the `0x9BFC8…0x9CD49` family) | compare incoming record **against the stored copy** (change-detect); if changed, store and set a dirty bit |
| gate + enqueue | → `FUN_0009C756` → ring `0x00AA94` | enqueue the changed record **only when** `g_outputPrio==2 && (g_acChargeFlags&8) && slot-enable` (AC First + grid-charge enabled) |
| drain + dispatch | `FUN_00098DE6` → `FUN_0009C7A2` | dequeue and route by a `(class,subtype)` type-code — **not** by time |
| inter-processor mirror | `FUN_000933A1` | same change-detect/store, driven by an AC-First sub-command frame; decodes a 1–18 subtype and stores the 3-word payload into the matching record |

Every function that reads these window-time targets is one of the above — a
config stage / change-detect / enqueue / dispatch handler. **None** compares a
stored window value against a current time or a running counter. The only
compares are *stored-vs-incoming* (has this parameter changed?), never
*stored-vs-now* (are we inside the window?).

> Aside: the sibling records in **block 0** (`0x00AD8F…92`, etc.) that look
> superficially like "windows" are in fact **voltage/frequency threshold windows**
> — `FUN_00093DCA` scales them ×10 and feeds them to a hysteresis comparator
> (`FUN_0009DEE9`) against a **measured** quantity (`0x00ABC8`) to set protection
> bits in `0x00B200`. That is an analog connect/disconnect window, still not a
> clock compare. Defaults are hard-set in `FUN_0009A338` (e.g. `0x1CCA`, `0x9C4`)
> — values that are plainly setpoints, not `HH:MM`.

## Where the window decision actually runs — the ARM (proven, cross-reference)

The ARM owns the RTC calendar (`0x2000D850`, advance `sub_08018BC0`; docs/36) and
evaluates the windows itself: `sub_080352D0` walks the three AC-First windows and
sets "active now" iff `start ≤ now < end` (start-inclusive, end-exclusive, with
midnight wrap), funnelling the verdict to **IR 126 bit 8** — and that verdict is
**not** pushed to the DSP
([HR152-157](../modbus-dongle/HR152_157-ACFirst-windows.md), docs/25 §3). The
charge/discharge schedule (HR 64-89) is evaluated the same way
([HR064-089](../modbus-dongle/HR064_089-charge-discharge-schedule.md)).

So the division of labour is:

```
ARM:  RTC  +  window start/end  ->  "inside window now?"  ->  acts on the result
      (and also forwards the raw start/end to the DSP as config)
DSP:  receives the raw start/end as opaque records; stores/diffs/queues them
      by type-code; never compares them to a time.  No clock. No time-of-day math.
```

This **confirms** the earlier claim (block-00 / docs/07) that AC-First window
start/stop is evaluated on the ARM, not shipped to the DSP as clock-compares, and
it **closes** the open follow-up left in [`docs/09`](../09-dsp-persistence-and-clock.md)
("where the window-evaluation math runs"): it is not on the DSP.

Background: [`docs/09`](../09-dsp-persistence-and-clock.md) (DSP has no NV storage /
no RTC; ARM owns both), [`docs/36`](../36-rtc-calendar-and-energy-rollover.md) (the
ARM RTC calendar), [`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md).
