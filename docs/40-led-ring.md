# The front-panel LED ring — PD15 (TIM4-CH4 PWM + DMA), driven by IR_STATE

The 12000XP's front panel has a circular RGB LED "halo" that glows/breathes and
spins — **green** in a normal running state, **yellow/amber** on a warning. This
note traces the whole chain, from the physical pin to the operating-state that
chooses the colour. Recovered from the factory `ceaa-07xx` image.

> **Corrects the wiring docs.** `docs/wiring/README.md` and [`docs/16`](16-arm-io-map.md)
> listed **PD15 / TIM4-CH4** as "aux PWM — fan / LCD backlight" (low confidence).
> It is not: PD15 is the **addressable-LED-ring data line**.

## The driver — a WS2812-family serial LED output on PD15

PD15 is TIM4 channel 4 (remap), driven as a **timer-PWM + DMA** serial stream —
the standard way an MCU bit-bangs WS2812/SK6812-style addressable LEDs without
bit-banging the CPU: each LED bit becomes one PWM period whose **duty** encodes a
0 or a 1, and DMA streams the per-bit duties out back-to-back.

```
LED colour buffer 0x20009e50   (per-bit PWM duties: 0x69 = '1' pulse, 0x2d = '0')
      | DMA1 Channel 7 (TIM4_UP request), mem->periph
      v
TIM4 CCR4 (0x40000840)  ── PWM ──>  PD15  (TIM4_CH4, AF push-pull)  ──>  LED ring
```

Proven from the peripheral setup in **`sub_08011e06`**:
- configures **PD15** on GPIOD (`0x40011400`, bit `0x8000`) as alternate-function
  push-pull;
- sets up **TIM4** (`0x40000800`) as a PWM time base (period `0x95`);
- arms **DMA1 Channel 7** (`0x40020080`) — the **TIM4_UP** request — to copy the
  colour buffer into **TIM4 CCR4** (`0x40000840`), the CH4 compare = PD15 duty.

The colour buffer is filled by **`sub_08011f8a` / `sub_08012010`**, which take a
colour value and **serialise its bits** into the buffer, writing `0x69` for a set
bit and `0x2d` for a clear bit (the two WS2812 pulse widths). CCR4 is written from
*nowhere else* in the image — this DMA path is its only producer.

## The animation — `sub_08012708`

A small state machine, `sub_08012708`, reads a **LED-mode byte at `0x2000050c`**
(0–7) and `tbb`-dispatches to per-mode colour writers (`sub_08012472`,
`sub_080124bc`, `sub_08012534`, `sub_08012598`, `sub_08012680`), which call the
bit-serialisers above. It also walks colour accumulators at `0x2000050c+0xa/+0xc/
+0xe`, stepping them by `0x11` each pass — the **breathing/throb and the
rotation** around the ring.

## The colour source — IR_STATE (input register 0) + two status flags

The LED-mode byte is **not** free-running; it is set by a mapper at
**`0x08016fcc`** (immediately after the `sub_08016ec6` run-enable/bypass relay
decider — the LED and the relays are updated from the *same* operating-state
cluster). It reads the operating-state struct **`0x2000d0e4`** and picks the mode:

| condition (field of `0x2000d0e4`) | LED mode `0x2000050c` |
|---|---|
| `[+0x98]` ≠ 0 (extended status dword) | 5 |
| else `[+0xa0]` **== 2** (IR_STATE = Programming) | 6 |
| else `[+0x9c]` ≠ 0 (extended status dword) | 4 |
| else `[+0xa0]` **≥ 3** (IR_STATE = a running mode) | 7 |
| else (Standby / Fault) | 0 (… continues) |

`0x2000d0e4+0xa0` is the live **operating-mode byte = IR_STATE (input register 0)**,
and `+0x98`/`+0x9c` are the **two extended-status dwords** written next to it by
the state classifier — exactly as [`docs/18`](18-power-path-relays.md) §"the mode
byte" and [`docs/16`](16-arm-io-map.md) establish for the relay gating. So:

**the ring's colour is sourced from the operating state surfaced on
[`IR 0` (State)](wiring/ARM-UART5-dongle/IR000-State.md)** — a *running* mode (≥3)
selects the green pattern (mode 7), while a warning/status condition in the
companion dwords selects the yellow/amber or red pattern (mode 4/5); Programming is
its own mode (6). The user-facing knobs (**"LED CtrEn / LED Ctr / LED Timer / LED
Mode / LED Light Factor / Green Function Enable"**, HMI strings) tune
enable/brightness/animation on top.

## Per-mode colours (traced)

Modes 4/5/7 play precomputed colour-frame animations from a flash table at
`0x0802ca7c` (`sub_08012598`, indexed `0x0802ca7c + 0x64·frame + 4·led`, mode 7 at
`+0`, mode 5 at `+0x1f4`, mode 4 at `+0x3e8`); mode 1 computes a live hue wheel
(`sub_08012708`); mode 6 is a separate writer (`sub_08012680`). Decoding the tables
(colour words are **`0x00RRGGBB`**, 8-bit per channel) pins the colours:

| LED mode | from state | colour words | **colour** | shape |
|---|---|---|---|---|
| **7** | IR_STATE ≥ 3 (running) | `0x00_nn_00` (G only) | **green** | rotating comet / gradient |
| **4** | status dword `+0x9c` ≠ 0 | `0x00_nn_nn_00` (R=G) | **yellow / amber** | rotating comet |
| **5** | status dword `+0x98` ≠ 0 | `0x00_nn_0000` (R only) | **red** | rotating comet |
| **6** | IR_STATE == 2 (Programming) | `0x0000ff00` (G) | green, distinct pattern | FW-update indicator |
| **1** | (not state-selected here) | live 6-phase wheel | **full rainbow** | rotating hue |
| **0** | Standby / else | — | off / idle | — |

So: **green = operating normally (mode 7), yellow/amber = warning (mode 4), red =
fault-level status (mode 5)** — exactly the observed behaviour, and the firmware
*already* contains a full rainbow cycler (mode 1). Each frame lights a brightness
gradient that advances one LED per tick around the ring (`head` index at
`0x2000050e`, wrapping at 25) → the **spinning comet**. Every colour is passed
through `sub_0801243c`, the per-channel brightness/gamma scaler fed by **"LED Light
Factor"** — the glow/throb.

```
IR_STATE (IR 0) + ext-status  ->  mapper 0x08016fcc  ->  LED mode 0x2000050c
   (0x2000d0e4 +0xa0/+0x98/+0x9c)                              |
                                                               v
                              sub_08012708 (animate) -> colour writers -> bit-serialise
                                                               |
                               colour buffer 0x20009e50 -> DMA1-Ch7 -> TIM4-CCR4 -> PD15
```

## What we could build with this ring

The hardware is far more capable than the stock green/yellow/red comet. What the
trace establishes about the canvas:

- **25 individually-addressable LEDs** in a circle (the loop runs LED `0..0x18`;
  the comet's `head` index wraps at 25). So any position-dependent pattern is
  possible — it is a 25-pixel circular display.
- **Full 24-bit RGB per LED** (`0x00RRGGBB`, 8-bit channels, 16.7 M colours). The
  stock animations only ever drive R and G (blue is `0x00` everywhere), but the
  data path is a true 3-byte-per-LED serial stream — so **blue is almost certainly
  wired** (these parts are RGB WS2812/SK6812-class). *Worth one hardware check
  before relying on blue, since no stock frame exercises it.*
- **Per-LED brightness** via `sub_0801243c` (the "LED Light Factor" scaler) — free
  global dimming and smooth fades/breathing.
- **Cheap updates** — TIM4-PWM + DMA shifts the whole frame out without CPU
  bit-banging, so re-colouring all 25 LEDs every animation tick is essentially free.

### Colours
Any RGB value. Beyond the stock green (`0x00ff00`) / amber (`0xffff00`) / red
(`0xff0000`): **blue** (`0x0000ff`), **cyan/white** for idle or charging, **purple**
for grid-export, etc. A per-state palette (e.g. blue = AC-charging, cyan = PV-only,
white = standby) is a one-line table change in the mode→colour map.

### Rainbow — already there
Mode 1 is a working **6-phase hue wheel** (R→Y→G→C→B→M→R, step `0x11`). It is just
not selected by the state mapper. Exposing it (e.g. a "party/boot" mode, or via the
HMI "LED Mode") gives a rotating rainbow for free. A **static rainbow ring** (each
of the 25 LEDs a different fixed hue, `hue = 360°·led/25`) is a trivial variant —
compute the wheel per-position instead of per-time.

### Patterns the 25-pixel ring enables
- **Gauge / arc** — light `K = round(25·value)` LEDs to show a percentage as a
  filled arc: **SOC gauge** (green arc = state-of-charge), **load/power meter**, or
  charge progress. The most useful upgrade — turns the ring into a dial.
- **Split / segments** — half green / half red, or N colour wedges, to encode two
  quantities at once (e.g. PV vs battery).
- **Multi-comet / dual-chase** — more than one lit head, or two colours chasing in
  opposite directions; the single-head logic generalises directly.
- **Breathe / pulse** — ramp the brightness scaler on all LEDs together (sine or
  triangle) for a calm "idle" glow, distinct from the running spin.
- **Blink / strobe** — attention patterns for faults (stock red comet → red
  double-blink), using the same frame buffer.
- **Spinner speed/direction by state** — faster spin under higher load, reverse on
  discharge; just change the `head` step/sign per tick.
- **Colour-temperature fade** — green→amber→red as a continuous function of a
  warning severity, rather than three discrete modes.

### For our open firmware
A clean reimplementation is a small module: a 25×RGB framebuffer, a `led_set(i,
rgb)` + `led_show()` (TIM4-CH4 PWM-DMA, 24 bits/LED, with the `0x69`/`0x2d` pulse
widths as the `1`/`0` encodings), a brightness scale, and an animation task that
picks colour+pattern from `IR_STATE`/faults — mirroring `sub_08012708`. The
gauge/arc and per-state palette are the highest-value additions; the ring is
otherwise a general RGB display we are free to drive however we like.

## Confidence

- **Proven:** PD15 = TIM4-CH4 AF; TIM4 PWM + DMA1-Ch7 → CCR4 ← buffer `0x20009e50`;
  the bit-serialiser emits two pulse-width duties; `sub_08012708` dispatches on the
  mode byte; the mapper `0x08016fcc` derives the mode from `0x2000d0e4` `+0xa0`
  (IR_STATE) / `+0x98` / `+0x9c`.
- **Proven (last mile):** 25 LEDs, 24-bit `0x00RRGGBB` per LED, and the per-mode
  colours read straight from the flash frame table (`0x0802ca7c`) — green (mode 7),
  amber (mode 4), red (mode 5), and the mode-1 rainbow wheel; the rotating comet is
  the frame gradient advancing one LED/tick.
- **Inferred:** that the LED part is specifically WS2812/SK6812 (the
  PWM+DMA+bit-serialise shape is unmistakably a serial-addressable-LED driver, but
  the exact chip/line timing is not bit-verified); and that **blue** is physically
  present (the data path is full 24-bit RGB, but no stock frame drives the B
  channel — a quick hardware check would confirm).

## Footnote — the `0x20009e50` buffer vs the "USART2 safety bank"

The LED colour buffer is at **`0x20009e50`**, which **overlaps** the address
[`docs/22`](22-arm-dsp-core-split.md) and the safety harness call the "USART2
telemetry bank" (`0x20009e54`). The functions that touch `0x20009e50` here are the
TIM4/DMA LED path, not a USART2 getter. This likely explains why the committed
`test_safety_cpu_telemetry_reaches_modbus` reads wrong on the 07 image (noted
while working T06, docs/39): the 07 safety-bank base is mis-pinned and may be
conflated with this LED buffer. Re-pinning the 07 telemetry/STATUS map (docs/22
"07-series re-pin") should resolve both.
