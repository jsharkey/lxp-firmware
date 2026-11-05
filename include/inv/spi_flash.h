/*
 * Minimal SPI NOR flash driver for the external config/settings flash.
 *
 * The com-MCU keeps its settings on a standard SPI NOR part on SPI1, chip-
 * selected by PA4 (active low) -- the same wiring the factory image uses
 * (docs/21). This is just enough of the command set to journal config records:
 * read, page program, 4 KB sector erase, plus WREN/RDSR.
 */
#ifndef INV_SPI_FLASH_H
#define INV_SPI_FLASH_H

#include <stdint.h>
#include <stddef.h>

/* Bring up SPI1 + its GPIOs (PA4 CS, PA5 SCK, PA6 MISO, PA7 MOSI). */
void spi_flash_init(void);

/* Read the 3-byte JEDEC id (0x9F) packed as (mfr<<16 | type<<8 | capacity).
 * Returns 0x000000 or 0xFFFFFF when no device responds. */
uint32_t spi_flash_jedec(void);

/* Read `n` bytes starting at flash byte-address `addr` into `buf`. */
void spi_flash_read(uint32_t addr, uint8_t *buf, size_t n);

/* Program up to one 256-byte page (`addr` must not cross a page boundary). */
void spi_flash_page_program(uint32_t addr, const uint8_t *buf, size_t n);

/* Erase the 4 KB sector containing `addr`. */
void spi_flash_sector_erase(uint32_t addr);

#endif /* INV_SPI_FLASH_H */
