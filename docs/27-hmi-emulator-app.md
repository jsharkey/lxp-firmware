# HMI emulator app — the running firmware's LCD + keys, on screen

> **Authoritative wiring:** the panels are specified in [`docs/wiring/ARM-LCD.md`](wiring/ARM-LCD.md). **Note:** this doc's description of the factory panel as "a SPI1 controller / undecoded" is stale — it is a bit-banged GPIOB bus (docs/28). The HD44780 stand-in content here is still valid.

Status: **built and host-tested.** An interactive app runs our firmware in the
emulator and renders what it draws to a character LCD, with the four
front-panel keys as on-screen buttons that drive the real key GPIOs — the
physical device, in a browser tab.

```
  key GPIO (PA8/PA11/PC8/PC9, active-low)
      │
      ▼
  hmi_keypad_poll()  ──▶  hmi_key()  ──▶  hmi_render()
                                              │  draws rows over
                                              ▼  bit-banged I²C
  PE0/PE1 ─ I²C ─▶ PCF8574 backpack ─▶ HD44780 20×4 ─▶ DDRAM ─▶ text
      ▲                                                            │
      │  tools/panel.py decodes this exact contract ◀─────────────┘
      ▼
  tools/hmi_app.py  ──▶  browser: 20×4 LCD + UP/DOWN/ENTER/ESC buttons
```

Everything on screen is produced by compiled firmware: the menu engine
(`src/hmi/hmi.c`) rendering through the real port (`src/hmi/hmi_port.c`) to a
modelled display over a modelled bus. Nothing is a Python reimplementation of
the HMI.

## Why an I²C character LCD

The *factory* panel is a SPI1 controller whose protocol is not yet
reverse-engineered (`docs/16`: the LCD sits on one of the SPI1 chip-selects;
the stream is undecoded, and the HMI task isn't reached by a harness boot — the
same scheduling blocker as the relay task, `docs/19`). Byte-matching the stock
HMI is an explicit non-goal (README "Strategy").

So for a *buildable, observable, bring-up-grade* panel this firmware drives a
ubiquitous hobby display instead: a **20×4 HD44780 character LCD behind a
PCF8574 I²C backpack** ("LCM1602"-style), bit-banged on two GPIOs. That choice
buys three things at once:

1. **Real firmware output** — the menu engine renders over a real (if simple)
   bus to a real controller model, not into a Python buffer.
2. **A trivially modelled device** — `tools/panel.py` decodes the I²C +
   PCF8574 + HD44780 contract by bit/nibble order (timing-independent), so the
   emulator *sees* the text.
3. **A faithful app** — buttons drive the genuine key pins; the firmware
   decides what to draw.

The wiring (pins, backpack bit map, row addresses, key pins) lives in one
header, **`include/inv/hmi_panel.h`**, shared by the firmware and the model, so
the two ends cannot drift. On real hardware the schematic will dictate a
different controller; swap `hmi_panel.h` + `hmi_port.c` then — the menu engine
and model are hardware-agnostic and unaffected.

## The contract (`include/inv/hmi_panel.h`)

- **Bus:** bit-banged I²C on **PE0 = SCL, PE1 = SDA** (push-pull; ACK ignored —
  the model never drives SDA).
- **Backpack:** PCF8574 at 7-bit address **0x27**, standard bit map
  `P0=RS, P1=RW, P2=E, P3=backlight, P4..P7 = HD44780 data nibble`.
- **Display:** HD44780 in 4-bit mode, 20×4; DDRAM row bases
  `0x00 / 0x40 / 0x14 / 0x54`. Each byte = high nibble then low nibble, latched
  on the E falling edge.
- **Keys:** the factory key pins (`docs/16`) **PA8 / PA11 / PC8 / PC9** =
  UP / DOWN / ENTER / ESC, active-low (a press pulls the pull-up pin to ground),
  read by a debounced scan that reports once per fresh press.
- **Selection:** a character LCD can't invert a row, so the selected row shows a
  `>` cursor in column 0.

A nominal bit-bang delay keeps emulation fast (the model decodes by order, not
timing); widen `HMI_LCD_DELAY_LOOPS` — or make it timer-based — for real HW.

## Running it

```bash
make hmi                 # build + serve on http://localhost:8080/
make hmi PORT=9000       # choose the port
```

or directly:

```bash
python3 tools/hmi_app.py --bin build/firmware.bin --elf build/firmware.elf --port 8080
```

Open the URL and click UP / DOWN / ENTER / ESC (or use the keyboard: arrows,
Enter, Esc). Needs `pip install unicorn` and the ARM toolchain's
`arm-none-eabi-nm` (to read the `.elf` symbols). No third-party web deps — the
backend is Python stdlib `http.server` holding one emulator instance.

The app seeds a plausible telemetry snapshot (state / battery V / SOC / grid
Hz) so the live-info rows look real; editable items (EPS voltage, output
priority, charge current, …) write the **same holding-register store the Modbus
slave uses**, so an HMI edit and a Modbus write stay consistent.

## Pieces

| File | Role |
|---|---|
| `include/inv/hmi_panel.h` | panel wiring (pins, PCF8574 map, row addresses, keys) — the shared contract |
| `src/hmi/hmi_port.c` | real port: bit-banged I²C → PCF8574 → HD44780, debounced keypad scan |
| `tools/panel.py` | emulator model: I²C → PCF8574 → HD44780 → 20×4 text; key injection helpers |
| `tools/hmi_engine.py` | boots our firmware in `arm_sim`, drives the real `hmi_*` functions, reads the screen |
| `tools/hmi_app.py` | the browser app (LCD + 4 keys) over `hmi_engine` |
| `tests/test_hmi_panel.py` | end-to-end tests: keys → engine → LCD text + register writes (`make test-sim-ours`) |

## Tests

`tests/test_hmi_panel.py` boots the firmware and drives the **real key GPIOs**,
then reads the screen back through the model — covering boot telemetry, cursor
movement, list scrolling, ENUM/U16 edits (which must write the holding
register), edit-cancel, and submenu enter/back. Runs under `make test-sim-ours`
and `make test-sim`.

## Extending

- **Factory image.** When the SPI1 LCD protocol is decoded (`docs/16` open
  item), add a SPI-side model next to `tools/panel.py` and point `hmi_app.py` at
  the factory image — the app's screen+keys shell is image-agnostic.
- **Full menu.** The model menu is a representative subset (`docs/06`); as
  `src/hmi/hmi_model.c` grows toward the 96-item stock tree, the app shows it
  with no changes.
- **Live animation.** `HmiSim.set_input_reg()` updates a telemetry register and
  re-renders; a periodic driver could animate the info rows.
