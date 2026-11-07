/*
 * Journaled settings store -- see inv/config_flash.h.
 *
 * Record (one 256-byte flash page):
 *   [0x00:0xFA] payload   [0xFA:0xFC] CRC-16/MODBUS(payload) LE   [0xFF] 0xA5
 * The three bytes [0xFC:0xFF] are padding; like the factory we write them 0xA5
 * (the whole word 0xA5A5A5A5 lands at 0xFC). The CRC covers only [0x00:0xFA],
 * so padding never affects validity.
 *
 * Ring per 8 KB slot (two 4 KB sectors, 32 pages). The write pointer walks the
 * slot bottom-to-top; the loader scans top-to-bottom and takes the first valid
 * record, so the newest write (highest valid page) wins. On wrap we clear the
 * lower sector before writing the new base record and the upper sector right
 * after, which both reclaims space and removes the stale records that would
 * otherwise shadow the fresh one -- the same invariant the factory maintains,
 * so the two firmwares read each other's flash.
 */
#include "inv/config_flash.h"
#include "inv/spi_flash.h"
#include "inv/modbus.h"            /* inv_modbus_crc16 */
#include <string.h>

#define PAGE    0x100u
#define SECTOR  0x1000u
#define REGION  0x2000u            /* 8 KB per slot */
#define MARKER  0xA5u
#define CRC_OFF  0xFAu
#define MARK_OFF 0xFFu

static uint8_t  s_img[CFG_SLOTS][PAGE];    /* live record image per slot */
static uint32_t s_wptr[CFG_SLOTS];         /* next flash write address   */
static bool     s_dirty[CFG_SLOTS];
static bool     s_loaded[CFG_SLOTS];        /* slot had a stored record at boot */
static bool     s_present;                 /* a config flash answered JEDEC */

static uint32_t slot_base(uint8_t slot) { return (uint32_t)slot * REGION; }

static bool record_valid(const uint8_t *rec)
{
    if (rec[MARK_OFF] != MARKER) return false;
    uint16_t crc = (uint16_t)(rec[CRC_OFF] | ((uint16_t)rec[CRC_OFF + 1] << 8));
    return inv_modbus_crc16(rec, CFG_PAYLOAD_LEN) == crc;
}

/* Newest valid page in a slot (scan top-down); -1 if none. Copies it to `out`. */
static int32_t newest_page(uint8_t slot, uint8_t *out)
{
    uint32_t base = slot_base(slot);
    uint8_t rec[PAGE];
    for (int32_t a = (int32_t)(base + REGION - PAGE); a >= (int32_t)base; a -= (int32_t)PAGE) {
        spi_flash_read((uint32_t)a, rec, PAGE);
        if (record_valid(rec)) { memcpy(out, rec, PAGE); return a; }
    }
    return -1;
}

void config_flash_init(void)
{
    spi_flash_init();

    /* No device (bus reads all-0 or all-1 for JEDEC) -> run with empty settings
     * and never touch the bus again. Also skips a costly full-slot scan when the
     * board has no config flash. */
    uint32_t id = spi_flash_jedec();
    s_present = (id != 0x000000u && id != 0xFFFFFFu);
    if (!s_present) {
        for (uint8_t s = 0; s < CFG_SLOTS; s++) {
            memset(s_img[s], 0, PAGE);
            s_wptr[s] = slot_base(s);
            s_dirty[s] = false;
            s_loaded[s] = false;
        }
        return;
    }

    for (uint8_t s = 0; s < CFG_SLOTS; s++) {
        int32_t p = newest_page(s, s_img[s]);
        if (p < 0) {                       /* blank slot: start a fresh ring */
            memset(s_img[s], 0, PAGE);
            s_wptr[s] = slot_base(s);
            s_loaded[s] = false;
        } else {
            s_wptr[s] = (uint32_t)p + PAGE; /* append above the newest record */
            s_loaded[s] = true;
        }
        s_dirty[s] = false;
    }
}

/* Whether a slot held a valid stored record at boot (vs. blank/first-boot). Lets
 * the settings layer apply factory defaults to blank slots and let persisted
 * records override only where they actually exist. */
bool config_slot_loaded(uint8_t slot)
{
    return (slot < CFG_SLOTS) && s_loaded[slot];
}

uint16_t config_get_u16(uint8_t slot, uint16_t off)
{
    return (uint16_t)(s_img[slot][off] | ((uint16_t)s_img[slot][off + 1] << 8));
}

void config_set_u16(uint8_t slot, uint16_t off, uint16_t value)
{
    if (config_get_u16(slot, off) == value) return;   /* no change, no wear */
    s_img[slot][off]     = (uint8_t)value;
    s_img[slot][off + 1] = (uint8_t)(value >> 8);
    s_dirty[slot] = true;
}

uint8_t config_get_u8(uint8_t slot, uint16_t off)
{
    return s_img[slot][off];
}

void config_set_u8(uint8_t slot, uint16_t off, uint8_t value)
{
    if (s_img[slot][off] == value) return;            /* no change, no wear */
    s_img[slot][off] = value;
    s_dirty[slot] = true;
}

static void flush_slot(uint8_t slot)
{
    uint8_t *img = s_img[slot];
    uint32_t base = slot_base(slot);

    /* finalise: CRC over the payload, then marker + padding (0xA5A5A5A5 @0xFC) */
    uint16_t crc = inv_modbus_crc16(img, CFG_PAYLOAD_LEN);
    img[CRC_OFF]     = (uint8_t)crc;
    img[CRC_OFF + 1] = (uint8_t)(crc >> 8);
    img[0xFC] = img[0xFD] = img[0xFE] = img[0xFF] = MARKER;

    uint32_t wp = s_wptr[slot];
    if (wp >= base + REGION) wp = base;                 /* normalise wrap */
    if (wp == base) spi_flash_sector_erase(base);       /* clear lower sector first */
    spi_flash_page_program(wp, img, PAGE);
    if (wp == base) spi_flash_sector_erase(base + SECTOR); /* drop stale upper records */

    s_wptr[slot] = wp + PAGE;
    s_dirty[slot] = false;
}

bool config_flash_poll(void)
{
    if (!s_present) return false;          /* nothing to journal to */
    bool wrote = false;
    for (uint8_t s = 0; s < CFG_SLOTS; s++) {
        if (s_dirty[s]) { flush_slot(s); wrote = true; }
    }
    return wrote;
}
