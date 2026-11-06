# ARM SPI1 ↔ config NOR flash (settings store)

**Authoritative** for this link. Research trail:
[`docs/21-arm-config-flash`](../21-arm-config-flash.md) (read side — primary),
[`docs/23-arm-config-writer`](../23-arm-config-writer.md) (write side + per-slot
field map), [`docs/24`](../24-oss-settings-region.md) (OSS forward-compat region),
[`docs/09`](../09-dsp-persistence-and-clock.md) (why the ARM owns persistence).

The ARM owns all non-volatile settings (the DSP has no NV storage and no
power-off RTC). They live in an external SPI NOR part, in a journaled,
wear-levelled store. **Boot cannot complete without valid config** — the loader
runs before task creation.

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **SPI1** master, **PA5 SCK / PA6 MISO / PA7 MOSI**, CS **PA4** (GPIO, active-low) | ✔ (ARM image) |
| config flash | commodity **SPI NOR** (≥ 8 MB, e.g. W25Q64) | ✔ behaviourally (modelled part) |

The "peer" is a standard SPI NOR chip, proven by running the factory image
against a modelled flash. There is **no second real device** — see the CS note
below.

## Physical

- Standard SPI NOR command set: JEDEC `0x9F`, read `0x03`, page-program `0x02`,
  WREN `0x06`, RDSR `0x05`, erase `0x20`(4 KB)/`0x52`(32 KB)/`0xD8`(64 KB)/`0xC7`
  (chip). Reimplementation clocks it at `BR_DIV8`; factory speed not fixed in the
  image.

> **Two SPI1 chip-selects (PA4, PC4) — but only one is the flash.** An earlier
> `docs/16` reading labelled the SPI1 CS cluster "LCD controller + config
> EEPROM/flash." That is **corrected**: the graphic LCD is a **bit-banged GPIOB**
> bus ([`ARM-LCD.md`](ARM-LCD-panel.md)), *not* on SPI1. Treat **PA4** as the config
> flash CS; the role of **PC4** (second CS) is not separately established.

## On-flash layout

- **Journaled store = six 8 KB slots** (`N·0x2000`), each a ring of 32 × 256-byte
  pages; the newest valid record wins.
- **Record format:** `[0x00]` 250-byte payload · `[0xFA]` 2-byte CRC-16/MODBUS
  (LE) over `payload[0x00:0xFA]` · `[0xFF]` `0xA5` validity marker. Valid iff
  marker == `0xA5` **and** CRC matches. (Same CRC-16 as the wire protocol.)
- Slots 0 and 5 also mirror a **default image in internal flash** at
  `0x0807F800` / `0x0807F900`.
- Per-slot field map (HR → byte offset) in docs/23: slot 0 = main settings,
  slot 5 = grid-code protection, etc.
- **OSS forward-compat region** `0x010000-0x03FFFF` with magic `"LXP1"` + marker
  `0x5A`, laid out so the factory firmware ignores it (docs/24).

## Key functions / files

- Factory read: loader `sub_0801683C` (chain `sub_0802E4DC` → `sub_08014696` →
  `sub_0801683C`), validator `sub_08016652`, CRC `sub_080160BC`, SPI primitives
  `sub_0801CB9E`/`sub_0801CB02`/`sub_0801CACE`.
- Factory write: committer `sub_080164bc`, dispatch `sub_0801ce32`, flush
  `sub_0801cfbc`, task `sub_0801d2ec`, internal-flash mirror `sub_0801d1d8`/
  `sub_0801d144`; per-slot descriptor table @ `0x080057b8`; RAM record images
  `0x2000c85c` (slot 0) … `0x2000cd5c` (slot 5).
- Reimplementation: driver
  [`src/config/spi_flash.c`](../../src/config/spi_flash.c) +
  [`include/inv/spi_flash.h`](../../include/inv/spi_flash.h); store
  [`src/config/config_flash.c`](../../src/config/config_flash.c) +
  [`include/inv/config_flash.h`](../../include/inv/config_flash.h); wired in
  [`src/main.c`](../../src/main.c) (`config_flash_init()` / `config_flash_poll()`).

## Open

- Identify the role of the second SPI1 CS (PC4).
- Per-slot payloads for the ~47 still-rejected holding registers (docs/23).
- Factory SPI clock rate.
