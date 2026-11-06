# ARM GPIOB ↔ graphic LCD panel

**Authoritative** for this link. Research trail:
[`docs/28`](../28-factory-hmi.md) (decoded panel — primary),
[`docs/16`](../16-arm-io-map.md) (pin map),
[`docs/06`](../06-hmi.md) (the HMI menu engine + keypad).

The factory front-panel display: a monochrome graphic LCD driven by **bit-banged
4-wire serial on GPIOB** — *not* over SPI1 (that bus is the config flash, see
[`ARM-SPI1.md`](ARM-SPI1-flash.md)).

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
  This is the front panel's only display.
- An earlier **stand-in** display — a 20×4 HD44780 over a bit-banged PCF8574 I²C
  backpack on PE0/PE1 (**our choice**, never factory wiring) — was **removed**
  once this panel was decoded. The hardware has no character LCD and does **no**
  I²C for a display (PE0/PE1 are not in the factory pin inventory). The front
  panel's keypad (PA8/PA11/PC8/PC9) lives in
  [`src/hmi/keypad.c`](../../src/hmi/keypad.c).

## Corrections folded in

- `docs/16` originally listed PB12/PB13/PB15 as a "status-LED / indicator bank"
  (static-analysis guess) → dynamic RE proved the LCD bus (docs/28); docs/16:193
  carries the reciprocal note.
