# Factory HMI — running the real graphic LCD in the emulator

> **Authoritative wiring:** the factory LCD bus is distilled in [`docs/wiring/ARM-LCD-panel.md`](wiring/ARM-LCD-panel.md). This doc remains the panel-decode detail.

Status: **working.** The factory ARM image's own display code runs under the
Unicorn harness (`tools/arm_sim.py`) and paints its real screens; a model of the
LCD reconstructs the picture, and the four front-panel keys drive the firmware's
own menu navigation. Both the **overview** and the **Common settings** screens
render pixel-faithfully and are reachable by key.

This is distinct from the open-firmware HMI (`docs/06`), our own reimplementation
— whose display driver (`src/hmi/lcd_tft.c`) drives this **same** graphic panel in
the same wire format (currently a "hello world" bring-up). Here nothing is
reimplemented: every pixel is the factory image's draw code executing.

## The display hardware (reverse-engineered)

The factory panel is a small **monochrome MIPI-DCS graphic LCD**, **240×160**
visible, driven **bit-banged 4-wire serial on GPIOB** — *not* over SPI1 (that bus
is the config NOR flash, `docs/21`):

| line | pin | role |
|---|---|---|
| SCLK | **PB12** | clock; data sampled on the rising edge |
| SDA  | **PB13** | serial data, MSB-first |
| DC   | **PB14** | 0 = command, 1 = data |
| /CS  | **PB15** | chip select, active low |

> `docs/16` listed PB12/PB13/PB15 as a "status-LED / indicator bank". That was a
> static-analysis guess; dynamic RE shows the four pins are the LCD bus. See the
> correction in `docs/16`.

The command set is MIPI-DCS: `SLPOUT 0x11`, `COLMOD 0x3A`, `CASET 0x2A`,
`RASET 0x2B`, `RAMWR 0x2C`, `DISPON/OFF`. The crucial decode is the **pixel
format**: it is **1 bit per pixel, packed 8 pixels to a byte, MSB-first**, and
the controller is addressed in **byte-columns** across (CASET) and **pixel rows**
down (RASET). So one RAMWR data byte paints 8 horizontal pixels. Reading each
byte as one pixel (the first wrong guess) both garbles text and makes the width
8× too small.

The firmware clears a **128-byte-wide** GRAM but the **visible panel is
byte-columns 48..127** → `(128-48)` bytes × 8 = **640 logical px → the 240×160
panel** (columns 0..47 are an off-panel left margin). Content is drawn with
windowed writes (CASET/RASET set a byte-column × row rectangle, RAMWR streams the
packed bytes row-major); there is no full RAM framebuffer. The command/data
primitive is `sub_080114d2(rs, byte)`; the full-screen clear is the inline loop
in `sub_08011698`. `tools/tft.py` captures the bytes, unpacks 8 px/byte, drops
the off-panel margin, and fits the result to 240×160.

## How it runs

Boot reaches the display only through the firmware's **preemptive RTOS** — the
same machinery `docs/19` built for the relay task:

1. `attach_config_flash()` gets boot past the config bring-up gate.
2. `enable_rtos()` + injected SysTick run the scheduler, which dispatches the
   HMI/display task.
3. The display task paints the overview; the key task reads PA8/PA11/PC8/PC9 and
   drives menu navigation.

A fake "ready" on the bxCAN status registers keeps the CAN-poll task from
spinning its whole slice (`docs/19`).

`tools/tft.py` models the controller: it decodes the bit-banged GPIOB stream (or,
equivalently, the command/data primitive) into the byte-column GRAM, unpacks 8 px/byte, and renders it as
the physical **monochrome** panel reads it (`mono()`), the dominant pixel value
being the background. `tools/factory_hmi.py` wraps the boot + key driving.

## Keys (recovered by driving the menus)

Active-low on the factory key pins (`docs/16`):

| pin | function |
|---|---|
| **PC9** | Up |
| **PA8** | Down / next |
| **PA11** | Enter / select (from the overview, opens the menu) |
| **PC8** | Esc / back |

Path to the Common settings screen: from the overview, **Enter** (PA11) opens the
Home/Info/Notice/Setting menu, **Down** (PA8) ×3 highlights *Setting*, **Enter**
(PA11) opens it.

## Speed

A full boot executes tens of millions of instructions — most of them the
faithfully-run preemptive RTOS switching tasks while the display waits on timers
— so several accuracy-preserving tricks make it usable (see `tools/arm_sim.py`
and `tools/factory_hmi.py`):

- **Scoped STOP hook** (`arm_sim.py`): the harness's `UC_HOOK_CODE` used to fire
  on every instruction; scoping it to the STOP page removes that per-step tax
  with no behaviour change.
- **PendSV tracked by a flag** (`arm_sim.py`): the RTOS engine must stop at a
  block boundary the instant a PendSV becomes takeable, which meant reading the
  `ICSR` register from emulated memory on *every* basic block. Instead a small
  write-hook mirrors `ICSR.PENDSVSET` into a Python flag the block hook tests for
  free — behaviour-identical (the write still lands in memory), ~25% off boot.
- **Fast emulated clock** (`TICK=4000`): the firmware's waits are measured in
  SysTick ticks, so a faster injected clock finishes them in far fewer
  instructions. Combined with a **prompt, jitter-tolerant settle** (stop as soon
  as the frame is quiet apart from the ticking on-screen clock — a long settle
  would burn enough emulated time to trip the menu idle-timeout).
- A **right-sized key hold**: a press holds the key only as long as the firmware
  needs to latch it (~2 M instructions, measured), not an arbitrary long press.

Result: factory boot ~29 s, each keypress a few seconds; the open-source build
boots in ~14 s. All of it runs the real firmware — none of these shortcuts skip
or fake any of its logic (what stays faked is only what the harness always
models: peripheral-ready flags, the config flash, the bxCAN FIFO).

### Boot cache

The boot is deterministic, so the **first** boot writes the exact post-boot
machine — CPU registers, all of memory, the RTOS engine's state and the LCD GRAM
— to `.hmi_cache/`, and later launches **restore it in ~0.02 s** instead of
re-booting. It is bit-identical (the same machine, continued), and a press from a
restored state navigates exactly as from a fresh boot.

The cache is **derived from the firmware image**, so a factory cache is as
proprietary as the image: `.hmi_cache/` is gitignored and **never committed** —
each user generates their own on first run. Keyed by the image's content hash, it
re-boots automatically when the firmware changes; `rm -rf .hmi_cache` or
`boot(cache=False)` forces a fresh boot. (The registers are saved explicitly, not
Unicorn's opaque context object, which does not survive being restored into a
fresh emulator.)

## Using it

The simulator is **firmware-agnostic** — it renders whatever image you point it
at. With no firmware it runs the **open-source build** (`build/firmware.bin`); a
path (vendor `.hex` or flat `.bin`) runs that instead.

```bash
make hmi-sim                       # the open-source firmware, http://localhost:8090/
make factory-hmi                   # the factory image
make hmi-sim FIRMWARE=path/App.hex # any other image
# or directly:
python3 tools/factory_hmi_app.py            # open-source build
python3 tools/factory_hmi_app.py App.hex    # a vendor image
```

The page shows the 240×160 panel (FSTN-tinted) and the four keys as buttons (also
arrow keys / Enter / Esc). It boots once (a spinner shows — the open build in
~14 s, the factory in ~20 s), then each press runs the firmware and repaints.
Needs `pip install unicorn numpy pillow`; the factory image also needs
`reference/ceaa-07xx_vE_260214.bin`.

Headless, from a script:

```python
from factory_hmi import FactoryHmi
FactoryHmi().boot().save_png("hello.png")                  # open-source build
h = FactoryHmi("reference/ceaa-07xx_vE_260214.bin").boot()            # factory image
h.save_png("overview.png")
for k in ["PA11", "PA8", "PA8", "PA8", "PA11"]:            # -> Common settings
    h.press(k)
h.save_png("common.png")
```

## The open firmware drives the same panel

Our firmware is a drop-in replacement, so it talks to the **same** LCD in the
**same wire format**: `src/hmi/lcd_tft.c` (+ `include/inv/lcd_tft.h`) bit-bangs
the 4-wire serial bus on PB12–15, sends the MIPI-DCS commands, and packs pixels
1bpp/8-per-byte exactly as the factory does — so `tools/tft.py` renders its
output identically. `main()` brings the panel up and posts a "Hello World!" as a
first milestone; `make hmi-sim` shows it.

## Pieces

| File | Role |
|---|---|
| `tools/tft.py` | LCD controller model: GPIOB serial stream → unpack 8 px/byte → drop off-panel margin → 240×160 monochrome image |
| `tools/factory_hmi.py` | boot **any** firmware image, read the screen, press keys (default: the open-source build) |
| `tools/factory_hmi_app.py` | browser app: the panel + four keys, driven by the real firmware |
| `src/hmi/lcd_tft.c` | the open firmware's driver for this panel (same bit-banged format) |

## Limits / next

- Live telemetry (PV/battery/grid numbers) is absent in the harness, so the
  overview's value fields render as their empty frames — the layout, icons, and
  static text are exact. Feeding the DSP-link / BMS values would populate them.
- Editing a setting (entering a field, changing a value) should work through the
  same keys; only navigation to the screens is exercised so far.
- The open firmware's panel bring-up is proven in the simulator; it still needs
  validating on real hardware, and the full factory init sequence (not just the
  CASET/RASET/RAMWR the sim needs) should be double-checked against a live panel.
