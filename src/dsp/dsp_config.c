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
 * records (built from the slot-committer, dsp_slots.c) and blocks 2/7/8 which are
 * the measurement-calibration gain tables (constant unity defaults, below). The
 * rest are empty for now: the frame is still emitted (header+blockid+CRC) so the
 * rotation and the DSP's completeness bitmask behave, carrying no payload. */
static const dsp_field_t *const block_fields[DSP_CONFIG_NBLOCKS] = {
    block0_fields, 0, 0, 0, 0, 0, 0, 0, 0
};
static const uint8_t block_nfields[DSP_CONFIG_NBLOCKS] = {
    (uint8_t)(sizeof block0_fields / sizeof block0_fields[0]), 0,0,0,0,0,0,0,0
};

/*
 * Blocks 2, 7, 8 — DSP measurement-calibration gain tables (T10).
 * These carry per-channel analog-measurement gains in Q10 fixed point, where
 * unity (gain 1.000) is 0x0400 = 1024 (the DSP applies `raw * gain >> 10`). On
 * the ARM they come from an ext-settings area that the factory default-inits to
 * unity and NO holding register exposes (docs/wiring/ARM-USART3-DSP/block-02.md,
 * block-07, block-08, field-provenance). Our firmware has no per-unit calibration
 * store, so it emits the uncalibrated default -- unity for every channel -- which
 * is byte-identical to the factory image's default-state frame for these blocks.
 * Each entry is a big-endian u16 at a sequential payload offset from 0x15.
 */
#define DSP_CAL_UNITY   0x0400u          /* Q10 gain of 1.000 (1024 >> 10) */

/* Block 2: a unity gain, a reserved word (0x17, emitted 0), then 11 unity gains. */
static const uint16_t block2_cal[] = {
    DSP_CAL_UNITY, 0x0000u, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
    DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
    DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
};
/* Block 7: 12 more unity gains, contiguous. */
static const uint16_t block7_cal[] = {
    DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
    DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
    DSP_CAL_UNITY, DSP_CAL_UNITY,
};
/* Block 8: 2 unity gains, then 2 words the DSP receives but does not consume in
 * this image (0x19 is a live status word, 0x1B a reserved ext-setting -- both
 * read unity at boot; emitting the default keeps the default-state frame exact
 * and neither affects DSP behaviour). */
static const uint16_t block8_cal[] = {
    DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY, DSP_CAL_UNITY,
};

static const uint16_t *const block_cal[DSP_CONFIG_NBLOCKS] = {
    0, 0, block2_cal, 0, 0, 0, 0, block7_cal, block8_cal
};
static const uint8_t block_cal_n[DSP_CONFIG_NBLOCKS] = {
    0, 0, (uint8_t)(sizeof block2_cal / sizeof block2_cal[0]),
    0, 0, 0, 0,
    (uint8_t)(sizeof block7_cal / sizeof block7_cal[0]),
    (uint8_t)(sizeof block8_cal / sizeof block8_cal[0]),
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

    /* The payload region (0x15..0x33) is fixed-size: zero it, then each block
     * writes only its own fields into it. This matches the factory, whose filler
     * leaves untouched payload bytes zero inside a fixed-length (0x36) frame, and
     * keeps the CRC out of the payload region so the wire bytes are comparable. */
    memset(out + DSP_OFF_PAYLOAD, 0, (size_t)(DSP_PAYLOAD_END - DSP_OFF_PAYLOAD));
    uint8_t *pl = out + DSP_OFF_PAYLOAD;    /* payload base = frame offset 0x15 */

    if (block_id == DSP_BLOCK_AC_CHARGE || block_id == DSP_BLOCK_AC_FIRST) {
        /* Slot-committer path: commit the schedule settings into the working slot
         * records (gated by each feature's enable bit, marking dirty), then
         * serialise this block's record -- slot-active mask + window times, BE.
         * Mirrors the factory settings->slot->block chain (docs/wiring/ARM-USART3-DSP). */
        dsp_slots_commit(&g_dsp_slots, src);
        const dsp_slot_record_t *rec = (block_id == DSP_BLOCK_AC_CHARGE)
                                     ? &g_dsp_slots.ac_charge : &g_dsp_slots.ac_first;
        dsp_slot_serialize(rec, pl);
    } else if (block_cal[block_id]) {
        /* Calibration-gain table (blocks 2/7/8): constant unity gains, BE16, at
         * sequential offsets from 0x15 -- the uncalibrated default (T10). */
        const uint16_t *cal = block_cal[block_id];
        for (uint8_t i = 0; i < block_cal_n[block_id]; i++)
            put16(pl + 2 * i, cal[i]);
    } else {
        /* pack this block's fields from the holding-register model */
        const dsp_field_t *f = block_fields[block_id];
        size_t off = 0;
        for (uint8_t i = 0; i < block_nfields[block_id]; i++) {
            uint16_t v = 0;
            if (src->read_holding) src->read_holding(src->ctx, f[i].reg, &v);
            if (f[i].width == 2) { put16(pl + off, v); off += 2; }
            else                 { pl[off++] = (uint8_t)v; }
        }
    }

    /* CRC-16 over the fixed header+payload (0x00..0x33); emit at 0x34..0x35. */
    n = DSP_PAYLOAD_END;
    uint16_t crc = dsp_crc16(out, n);
#if DSP_CRC_MSB_FIRST
    out[n++] = (uint8_t)(crc >> 8); out[n++] = (uint8_t)crc;
#else
    out[n++] = (uint8_t)crc; out[n++] = (uint8_t)(crc >> 8);
#endif
    return n;   /* == DSP_FRAME_LEN (0x36) */
}

size_t dsp_push_next(dsp_push_t *p, const dsp_cfg_src_t *src, uint8_t *out, size_t cap)
{
    size_t len = dsp_build_config_frame(src, p->next_block, out, cap);
    p->next_block = (uint8_t)((p->next_block + 1) % DSP_CONFIG_NBLOCKS);  /* full-snapshot rotation */
    return len;
}
