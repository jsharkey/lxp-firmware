/*
 * Grid-charge slot records + committers for the ARM->DSP config push.
 * See inv/dsp_slots.h and docs/wiring/ARM-USART3-DSP/field-provenance.md.
 */
#include "inv/dsp_slots.h"
#include "inv/modbus_map.h"

/* The AC-charge schedule enable: FuncEn (HR 21) bit 7 (ACChargeEn), per the
 * block-0 field notes in dsp_config.c / docs/07. AC-First is gated by the
 * HalfHourACChrStart / ACChargeType group in HR_SYS_ENABLE (HR 120); we treat a
 * nonzero SYS_ENABLE as "AC-First schedule active" for the slot-active mask.
 * These gates affect ONLY the slot-active mask word, never whether the window
 * TIMES are serialized -- the factory serializes the committed times regardless
 * of enable (live capture: HR 68-73 reach block 4 with no enable set), and the
 * enable merely tells the DSP which slots to act on. */
#define FUNC_EN_ACCHARGE   (1u << 7)

static uint16_t rd(const dsp_cfg_src_t *src, uint16_t reg)
{
    uint16_t v = 0;
    if (src->read_holding) src->read_holding(src->ctx, reg, &v);
    return v;
}

static void commit_record(dsp_slot_record_t *rec, const dsp_cfg_src_t *src,
                          uint16_t first_window_reg, bool enabled)
{
    bool changed = (rec->enabled != enabled);
    for (int i = 0; i < DSP_SLOT_WINDOWS; i++) {
        uint16_t v = rd(src, (uint16_t)(first_window_reg + i));
        if (rec->window[i] != v) { rec->window[i] = v; changed = true; }
    }
    rec->enabled = enabled;
    rec->dirty   = changed;
}

void dsp_slots_commit(dsp_slots_t *s, const dsp_cfg_src_t *src)
{
    if (!s || !src) return;
    commit_record(&s->ac_charge, src, HR_ACCHG_START_0,
                  (rd(src, HR_FUNC_EN) & FUNC_EN_ACCHARGE) != 0);
    commit_record(&s->ac_first, src, HR_ACFIRST_START_0,
                  rd(src, HR_SYS_ENABLE) != 0);
}

static void put16_be(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }

size_t dsp_slot_serialize(const dsp_slot_record_t *rec, uint8_t *p)
{
    /* slot-active mask (frame @0x15): bit per window when the feature is enabled,
     * else 0. The window TIMES follow at payload +0x02 (frame @0x17) regardless. */
    uint16_t mask = rec->enabled ? ((1u << DSP_SLOT_WINDOWS) - 1u) : 0u;
    put16_be(p, mask);
    for (int i = 0; i < DSP_SLOT_WINDOWS; i++)
        put16_be(p + 2 + 2 * i, rec->window[i]);
    return (size_t)(2 + 2 * DSP_SLOT_WINDOWS);
}
