/*
 * ARM -> DSP grid-charge "slot records" + committers.
 *
 * Mirrors the factory design (docs/modbus-dsp/field-provenance.md): the config
 * push does NOT serialize raw holding registers. The schedule settings are first
 * COMMITTED into a working "slot record" (the factory keeps these at RAM
 * 0x2000a330; a ~34-function committer family copies settings -> slot, gated by a
 * per-feature enable bit, and sets a dirty bit in a mask that becomes the DSP's
 * per-slot active mask 0xAD54). The frame builder then serializes the slot
 * records, not the registers. So the data path is:
 *
 *     holding register --(commit: gated, marks dirty)--> slot record
 *                      --(build: positional, big-endian)--> DSP config block
 *
 * This file is the clean-room equivalent for the one piece we have pinned by live
 * capture (tests/test_dsp_push.py): the time-window records.
 *   * AC-charge windows HR 68-73  -> block 4 payload @0x17..0x21
 *   * AC-First  windows HR 152-157 -> block 5 payload @0x17..0x21
 * Each big-endian u16, packed low=hour / high=minute.
 */
#ifndef INV_DSP_SLOTS_H
#define INV_DSP_SLOTS_H

#include <stdint.h>
#include <stdbool.h>
#include "inv/dsp_link.h"     /* dsp_cfg_src_t */

#define DSP_SLOT_WINDOWS   6  /* w0s w0e w1s w1e w2s w2e */

/* One schedule feature's committed record. */
typedef struct {
    uint16_t window[DSP_SLOT_WINDOWS];  /* committed window times (hour|minute)  */
    bool     enabled;                   /* feature enable -> slot-active mask     */
    bool     dirty;                     /* set by commit when the record changed  */
} dsp_slot_record_t;

/* The whole working slot set the config push serializes. */
typedef struct {
    dsp_slot_record_t ac_charge;   /* HR 68-73,  enable HR_FUNC_EN bit -> block 4 */
    dsp_slot_record_t ac_first;    /* HR 152-157, enable HR_SYS_ENABLE -> block 5 */
} dsp_slots_t;

/* Commit the schedule holding registers into the slot records via
 * src->read_holding(), gated by each feature's enable bit. Sets .dirty on any
 * record whose committed values changed since the last commit. Idempotent:
 * calling it twice with unchanged settings leaves .dirty clear the second time. */
void dsp_slots_commit(dsp_slots_t *s, const dsp_cfg_src_t *src);

/* Serialize one slot record into a block payload starting at `p` (which is
 * frame offset 0x15): a 2-byte big-endian slot-active mask (nonzero iff the
 * feature is enabled), then the 6 window u16s big-endian at payload +0x02.. (so
 * the first window lands at frame @0x17, matching the factory). Returns the
 * number of payload bytes written (always 2 + 2*DSP_SLOT_WINDOWS). */
size_t dsp_slot_serialize(const dsp_slot_record_t *rec, uint8_t *p);

#endif /* INV_DSP_SLOTS_H */
