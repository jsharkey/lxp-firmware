/*
 * ARM -> DSP configuration push (type-1 frames, 8 blocks). See inv/dsp_link.h
 * and docs/08-arm-dsp-config-protocol.md.
 *
 * The framing, CRC, block-id scheme and full-snapshot rotation are faithful to
 * the RE. The per-block FIELD LISTS below are the editable part: each block names
 * the holding registers packed into its payload, in order. Only block 0 has a
 * best-effort field list (the AC-First / output-priority group from docs/07);
 * blocks 1..7 are left as TODO stubs (they still frame correctly, with an empty
 * payload) until their field order is decoded.
 */
#include "inv/dsp_link.h"
#include "inv/dsp_slots.h"   /* grid-charge slot records + committers (blocks 4/5) */
#include "inv/modbus.h"      /* reuse the shared CRC-16 */
#include "inv/modbus_map.h"
#include <string.h>

/* CRC-16/Modbus is the same routine the Modbus layer and the DSP both use. */
uint16_t dsp_crc16(const uint8_t *buf, size_t len) { return inv_modbus_crc16(buf, len); }

/* Emit the CRC. docs/08 states the DSP TX builder uses MSB-first; the ARM->DSP
 * order is not explicitly documented. Default to little-endian (lo,hi) as in the
 * rest of the EG4 Modbus family; flip DSP_CRC_MSB_FIRST if a capture disagrees. */
#define DSP_CRC_MSB_FIRST 0

/* Payload multi-byte fields are BIG-ENDIAN on the ARM->DSP wire -- confirmed by
 * live USART3 capture of the schedule windows (tests/test_dsp_push.py: HR 68 =
 * 0x2215 serialises as bytes 22 15 at block 4 @0x17). The DSP's field readers
 * FUN_0009E7C2/FUN_0009E6BA are big-endian (docs/08). (The dongle Modbus path is
 * little-endian -- a different wire; do not confuse the two.) */

/* Each payload field: a holding register and how many bytes to emit (1 or 2). */
typedef struct { uint16_t reg; uint8_t width; } dsp_field_t;

/*
 * Block 0 — output priority / AC-First + grid-charge enable group.
 * On the DSP this lands in the 0x00AD?? cluster (g_outputPrio=0xADA8,
 * g_acChargeFlags=0xAD84, grid-charge schedule records) — see docs/07.
 * Exact byte offsets inside the block are not yet pinned, so this ordering is a
 * best-effort starting point to refine against a bus capture.
 */
static const dsp_field_t block0_fields[] = {
    { HR_OUTPUT_PRIO_CFG, 1 },   /* 0=Bat First, 1=PV First, 2=AC First  -> g_outputPrio */
    { HR_SYS_ENABLE,      2 },   /* ACChargeType/flags bits              -> g_acChargeFlags */
    { HR_FUNC_EN,         2 },   /* FuncEn.ACChargeEn (bit 7) etc.                         */
    { HR_EOD,             1 },   /* end-of-discharge SOC                                   */
    /* TODO: AC-charge time windows + SOC/Volt (HR ~68-73, 158-161) once mapped */
};

/* Blocks 1..8 — target RAM clusters known (docs/08) but field order not yet
 * recovered, EXCEPT blocks 4 and 5 which carry the grid-charge time-window slot
 * records and are built from the slot-committer (dsp_slots.c), not this table.
 * The rest are empty for now: the frame is still emitted (header+blockid+CRC) so
 * the rotation and the DSP's completeness bitmask behave, carrying no payload. */
static const dsp_field_t *const block_fields[DSP_CONFIG_NBLOCKS] = {
    block0_fields, 0, 0, 0, 0, 0, 0, 0, 0
};
static const uint8_t block_nfields[DSP_CONFIG_NBLOCKS] = {
    (uint8_t)(sizeof block0_fields / sizeof block0_fields[0]), 0,0,0,0,0,0,0,0
};

/* Blocks built from slot records instead of the field table (dsp_slots.c). */
#define DSP_BLOCK_AC_CHARGE  4   /* HR 68-73  window times */
#define DSP_BLOCK_AC_FIRST   5   /* HR 152-157 window times */

/* The working slot records the push serialises (committed from settings on each
 * build, mirroring the factory's commit-during-build; see dsp_slots.c). */
static dsp_slots_t g_dsp_slots;

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }

size_t dsp_build_config_frame(const dsp_cfg_src_t *src, uint8_t block_id,
                              uint8_t *out, size_t cap)
{
    if (!src || block_id >= DSP_CONFIG_NBLOCKS || cap < DSP_FRAME_MAX) return 0;

    size_t n = 0;
    out[DSP_OFF_ADDR] = src->address;
    out[DSP_OFF_TYPE] = DSP_FRAME_TYPE_CONFIG;

    /* 18-byte header: SN[10] then a 6-byte timestamp then 2 aux bytes */
    uint8_t *h = out + DSP_OFF_HEADER;
    memcpy(h, src->sn, DSP_SN_LEN);
    h[10] = src->year; h[11] = src->month; h[12] = src->day;
    h[13] = src->hour; h[14] = src->minute; h[15] = src->second;
    h[16] = 0; h[17] = 0;                      /* aux (unmapped)             */

    out[DSP_OFF_BLOCKID] = block_id;
    n = DSP_OFF_PAYLOAD;

    if (block_id == DSP_BLOCK_AC_CHARGE || block_id == DSP_BLOCK_AC_FIRST) {
        /* Slot-committer path: commit the schedule settings into the working slot
         * records (gated by each feature's enable bit, marking dirty), then
         * serialise this block's record -- slot-active mask + window times, BE.
         * Mirrors the factory settings->slot->block chain (docs/modbus-dsp). */
        dsp_slots_commit(&g_dsp_slots, src);
        const dsp_slot_record_t *rec = (block_id == DSP_BLOCK_AC_CHARGE)
                                     ? &g_dsp_slots.ac_charge : &g_dsp_slots.ac_first;
        n += dsp_slot_serialize(rec, out + n);
    } else {
        /* pack this block's fields from the holding-register model */
        const dsp_field_t *f = block_fields[block_id];
        for (uint8_t i = 0; i < block_nfields[block_id]; i++) {
            uint16_t v = 0;
            if (src->read_holding) src->read_holding(src->ctx, f[i].reg, &v);
            if (f[i].width == 2) { put16(out + n, v); n += 2; }
            else                 { out[n++] = (uint8_t)v; }
        }
    }

    /* CRC-16 over everything so far */
    uint16_t crc = dsp_crc16(out, n);
#if DSP_CRC_MSB_FIRST
    out[n++] = (uint8_t)(crc >> 8); out[n++] = (uint8_t)crc;
#else
    out[n++] = (uint8_t)crc; out[n++] = (uint8_t)(crc >> 8);
#endif
    return n;
}

size_t dsp_push_next(dsp_push_t *p, const dsp_cfg_src_t *src, uint8_t *out, size_t cap)
{
    size_t len = dsp_build_config_frame(src, p->next_block, out, cap);
    p->next_block = (uint8_t)((p->next_block + 1) % DSP_CONFIG_NBLOCKS);  /* full-snapshot rotation */
    return len;
}
