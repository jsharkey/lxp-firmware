# Factory HMI — running the real graphic LCD in the emulator

Status: **working.** The factory ARM image's own display code runs under the
Unicorn harness (`tools/arm_sim.py`) and paints its real screens; a model of the
LCD reconstructs the picture, and the four front-panel keys drive the firmware's
own menu navigation. Both the **overview** and the **Common settings** screens
render pixel-faithfully and are reachable by key.

This is distinct from the open-firmware HMI (`docs/22`), which is our own 20×4
character-LCD reimplementation. Here nothing is reimplemented: every pixel is the
factory image's draw code executing.

## The display hardware (reverse-engineered)

The factory panel is a small **MIPI-DCS graphic TFT**, **128×160, 1 byte per
pixel**, driven **bit-banged 4-wire serial on GPIOB** — *not* over SPI1 (that bus
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
`RASET 0x2B`, `RAMWR 0x2C`, `DISPON/OFF` — an ST77xx/ILI-class controller. The
firmware draws **straight into the controller's GRAM** with windowed writes
(CASET/RASET set a rectangle, RAMWR streams it); there is no full RAM
framebuffer. The command/data primitive is `sub_080114d2(rs, byte)`; a full
screen clear is the inline loop in `sub_08011698` (fills 20480 pixels).

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
equivalently, the command/data primitive) into the 128×160 GRAM and renders it as
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

A full boot executes tens of millions of instructions, so two things make it
usable (see `tools/arm_sim.py` and `tools/factory_hmi.py`):

- **Scoped STOP hook** (`arm_sim.py`): the harness's `UC_HOOK_CODE` used to fire
  on every instruction; scoping it to the STOP page removes that per-step tax
  with no behaviour change.
- **Fast emulated clock** (`TICK=4000`): the firmware's waits are measured in
  SysTick ticks, so a faster injected clock finishes them in far fewer
  instructions. Combined with a **prompt, jitter-tolerant settle** (stop as soon
  as the frame is quiet apart from the ticking on-screen clock — a long settle
  would burn enough emulated time to trip the menu idle-timeout).

Result: boot ~18 s, each keypress ~6 s, ~50 s to drive from reset to the Common
settings screen (down from ~75 s / ~30 s / ~225 s).

## Using it

```bash
make factory-hmi            # boot the factory HMI, serve it on http://localhost:8090/
make factory-hmi PORT=9000
# or:
python3 tools/factory_hmi_app.py --port 8090
```

The page shows the 128×160 panel (FSTN-tinted) and the four keys as buttons
(also arrow keys / Enter / Esc). It boots once (~18 s, a spinner shows), then each
press runs the firmware (~6 s) and repaints. Needs `pip install unicorn numpy
pillow` and `reference/com_flat.bin` + `reference/symbols.csv`.

Headless, from a script:

```python
from factory_hmi import FactoryHmi
h = FactoryHmi().boot()
h.save_png("overview.png")
for k in ["PA11", "PA8", "PA8", "PA8", "PA11"]:   # -> Common settings
    h.press(k)
h.save_png("common.png")
```

## Pieces

| File | Role |
|---|---|
| `tools/tft.py` | LCD controller model: GPIOB serial stream → 128×160 GRAM → monochrome image |
| `tools/factory_hmi.py` | boot the factory image through its RTOS, read the screen, press keys |
| `tools/factory_hmi_app.py` | browser app: the panel + four keys, driven by the real firmware |

## Limits / next

- Live telemetry (PV/battery/grid numbers) is absent in the harness, so the
  overview's value fields render as their empty frames — the layout, icons, and
  static text are exact. Feeding the DSP-link / BMS values would populate them.
- Editing a setting (entering a field, changing a value) should work through the
  same keys; only navigation to the screens is exercised so far.
- The pixel bytes carry an 8-bit value (the firmware passes "colors" like `0xE0`,
  `0x1F`); the physical panel is monochrome, so `mono()` treats any non-background
  value as ink. If a true grayscale/color panel is confirmed, map the bytes
  accordingly.
