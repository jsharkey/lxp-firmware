/*
 * Journaled settings store on the external SPI NOR flash.
 *
 * Byte-for-byte compatible with the factory format (docs/21, docs/23): six 8 KB
 * slots, each a ring of 256-byte records; a record is 250 payload bytes, a
 * CRC-16/MODBUS of that payload at [0xFA:0xFC] (little-endian), and a 0xA5
 * marker at [0xFF]. The loader takes the newest valid record per slot (scan
 * top-down, first valid wins); the writer appends a fresh record and erases on
 * wrap. Because the on-flash layout matches the factory's, records written by
 * either firmware are read correctly by the other.
 *
 * Settings are addressed as (slot, byte-offset) into the 250-byte payload; the
 * map is docs/23. Only fields the open firmware understands are touched -- a
 * read-modify-write preserves every other byte of the slot, so factory settings
 * we don't model survive a round-trip.
 */
#ifndef INV_CONFIG_FLASH_H
#define INV_CONFIG_FLASH_H

#include <stdint.h>
#include <stdbool.h>

#define CFG_SLOTS        6
#define CFG_PAYLOAD_LEN  0xFAu     /* bytes [0x00:0xFA] covered by the CRC */

/* Which holding registers persist, and their slot/offset/width/scale, is the
 * table in inv/settings_map.h (docs/23). This header is just the store. */

/* Load every slot's newest valid record from flash into the in-RAM images and
 * initialise each ring's write pointer. Call once at boot (brings up SPI1). */
void config_flash_init(void);

/* Read/update a little-endian u16 field in a slot's payload image. A set that
 * changes the value marks the slot dirty; config_flash_poll() journals it. */
uint16_t config_get_u16(uint8_t slot, uint16_t off);
void     config_set_u16(uint8_t slot, uint16_t off, uint16_t value);

/* Same, for a single-byte payload field (e.g. slot-5's packed power-command
 * block). A read-modify-write preserves every neighbouring byte. */
uint8_t  config_get_u8(uint8_t slot, uint16_t off);
void     config_set_u8(uint8_t slot, uint16_t off, uint8_t value);

/* Flush any dirty slot to flash as a new journaled record. Returns true if it
 * wrote anything. Call from the main loop. */
bool config_flash_poll(void);

/* True iff `slot` held a valid stored record at boot (false = blank/first-boot). */
bool config_slot_loaded(uint8_t slot);

#endif /* INV_CONFIG_FLASH_H */
