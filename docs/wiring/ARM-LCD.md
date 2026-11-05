# ARM GPIOB ↔ graphic LCD panel

**Authoritative** for this link. Research trail:
[`docs/28`](../28-factory-hmi.md) (decoded panel — primary),
[`docs/16`](../16-arm-io-map.md) (pin map),
[`docs/27`](../27-hmi-emulator-app.md) (the reimplementation stand-in).

The factory front-panel display: a monochrome graphic LCD driven by **bit-banged
4-wire serial on GPIOB** — *not* over SPI1 (that bus is the config flash, see
[`ARM-SPI1.md`](ARM-SPI1.md)).

## Endpoints

| end | wiring | confidence |
|---|---|---|
| ARM "com" MCU | 4 GPIOB pins, bit-banged (`sub_080114d2` / `sub_08011698`) | ✔ |
| panel | 240×160 monochrome **MIPI-DCS** LCD, 1 bpp | ✔ |

## Physical — the 4-wire bus

| signal | pin | notes |
|---|---|---|
| SCLK | **PB12** | clock, sampled on rising edge |
| SDA | **PB13** | data, MSB-first |
| DC | **PB14** | 0 = command, 1 = data |
| /CS | **PB15** | active low |

Pins configured output push-pull 50 MHz. (PB14 also appears as a shared
input in the IO sweep — it is the DC line.)

## Protocol

MIPI-DCS command set: `SLPOUT 0x11`, `COLMOD 0x3A`, `CASET 0x2A`, `RASET 0x2B`,
`RAMWR 0x2C`, `DISPON/OFF`. Pixel format **1 bpp, 8 px/byte, MSB-first**,
addressed in byte-columns across (CASET) × pixel rows down (RASET). The firmware
clears a 128-byte-wide GRAM; the visible panel maps to byte-columns 48..127,
fit to 240×160. Primitive `sub_080114d2(rs, byte)`; full clear is an inline loop
in `sub_08011698`.

## Direction & roles

ARM → panel (write-only display). Driven by the HMI render code against the
front-panel keys ([overview "Local GPIO"](README.md#local-gpio-not-inter-processor-links)).

## Reimplementation

- **Open firmware drives the same factory panel identically:**
  [`src/hmi/lcd_tft.c`](../../src/hmi/lcd_tft.c) (`PIN_SCLK 1<<12`,
  `PIN_SDA 1<<13`, `PIN_DC 1<<14`, `PIN_CS 1<<15`; PB12..PB15 output push-pull).
- **Stand-in panel (NOT factory wiring).** The reimplementation also ships a
  clean 20×4 **HD44780** panel over a bit-banged **PCF8574 I²C backpack**, as an
  observable development target. Its wiring is **our choice**, not recovered from
  the device: SCL = **PE0**, SDA = **PE1** (push-pull, ACK ignored), PCF8574 at
  7-bit `0x27` (`P0=RS, P1=RW, P2=E, P3=backlight, P4..P7=data`), HD44780 4-bit
  mode, DDRAM row bases `0x00/0x40/0x14/0x54`; keys shared with the factory key
  pins. Files: [`include/inv/hmi_panel.h`](../../include/inv/hmi_panel.h),
  [`src/hmi/hmi_port.c`](../../src/hmi/hmi_port.c). The factory does **no I²C**
  (so PE0/PE1 are not in the factory pin inventory).

## Corrections folded in

- `docs/16` originally listed PB12/PB13/PB15 as a "status-LED / indicator bank"
  (static-analysis guess) → dynamic RE proved the LCD bus (docs/28); docs/16:193
  carries the reciprocal note.
- **`docs/27` is stale** where it calls the factory panel "a SPI1 controller …
  undecoded" — superseded here and by docs/28. (Its HD44780 stand-in content is
  still valid.)
