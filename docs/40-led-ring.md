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
companion dwords selects the yellow/amber pattern (mode 4/5); Programming is its
own mode (6). The user-facing knobs (**"LED CtrEn / LED Ctr / LED Timer / LED
Mode / LED Light Factor / Green Function Enable"**, HMI strings) tune
enable/brightness/animation on top.

```
IR_STATE (IR 0) + ext-status  ->  mapper 0x08016fcc  ->  LED mode 0x2000050c
   (0x2000d0e4 +0xa0/+0x98/+0x9c)                              |
                                                               v
                              sub_08012708 (animate) -> colour writers -> bit-serialise
                                                               |
                               colour buffer 0x20009e50 -> DMA1-Ch7 -> TIM4-CCR4 -> PD15
```

## Confidence

- **Proven:** PD15 = TIM4-CH4 AF; TIM4 PWM + DMA1-Ch7 → CCR4 ← buffer `0x20009e50`;
  the bit-serialiser emits two pulse-width duties; `sub_08012708` dispatches on the
  mode byte; the mapper `0x08016fcc` derives the mode from `0x2000d0e4` `+0xa0`
  (IR_STATE) / `+0x98` / `+0x9c`.
- **Inferred:** that the LED part is specifically WS2812/SK6812 (the
  PWM+DMA+bit-serialise shape is unmistakably a serial-addressable-LED driver, but
  the exact chip/line timing is not bit-verified); and the precise RGB each mode
  writes (green vs amber) — the IR_STATE→mode mapping is proven, the per-mode
  colour constants are the remaining detail to trace in the colour writers.

## Footnote — the `0x20009e50` buffer vs the "USART2 safety bank"

The LED colour buffer is at **`0x20009e50`**, which **overlaps** the address
[`docs/22`](22-arm-dsp-core-split.md) and the safety harness call the "USART2
telemetry bank" (`0x20009e54`). The functions that touch `0x20009e50` here are the
TIM4/DMA LED path, not a USART2 getter. This likely explains why the committed
`test_safety_cpu_telemetry_reaches_modbus` reads wrong on the 07 image (noted
while working T06, docs/39): the 07 safety-bank base is mis-pinned and may be
conflated with this LED buffer. Re-pinning the 07 telemetry/STATUS map (docs/22
"07-series re-pin") should resolve both.
