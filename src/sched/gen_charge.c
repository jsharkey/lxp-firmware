/*
 * Generator-charge start/stop voltage gate with hysteresis. See
 * include/inv/gen_charge.h and docs/wiring/ARM-UART5-dongle/HR194_198-generator-charge.md
 * (T16). Mirrors the factory evaluator sub_08035050's voltage block
 * (07 block 0x08035086, verdict 0x2000dbc0) byte-for-byte on the decision.
 */
#include "inv/gen_charge.h"

bool inv_gen_charge_volt_gate(bool active, uint16_t vbat_bank,
                              uint16_t start_v, uint16_t end_v, bool stop_ok)
{
    /* The factory zero-extends the bank word (ldrh) then signed-divides by 10
     * (sdiv) and signed-compares; reproduce that exactly. */
    int32_t v = (int32_t)(uint16_t)vbat_bank / 10;

    if (!active)
        return v < (int32_t)start_v;          /* start charging when battery is low */
    /* stay charging until the battery is high AND the DSP confirms it is safe. */
    return !((v >= (int32_t)end_v) && stop_ok);
}

bool inv_gen_charge_soc_gate(bool active, uint8_t soc,
                             uint8_t start_soc, uint8_t end_soc, bool stop_ok)
{
    /* SOC sibling: the factory compares the battery SOC byte (0x2000d7b0) unsigned
     * (blo/bhs) against the two 1-byte thresholds; same charge-direction hysteresis
     * and same DSP stop-confirmation as the voltage gate. */
    if (!active)
        return soc < start_soc;               /* start charging when SOC is low */
    return !((soc >= end_soc) && stop_ok);
}

bool inv_gen_charge_permit(inv_gen_charge_state_t *st, bool charge_by_soc,
                           uint16_t vbat_bank, uint16_t v_start, uint16_t v_end,
                           uint8_t soc, uint8_t s_start, uint8_t s_end,
                           bool stop_ok)
{
    /* Step both latches so neither goes stale across a mode change, then return the
     * one HR 120 bit 7 selects (0 = by voltage, 1 = by SOC). */
    st->v_active = inv_gen_charge_volt_gate(st->v_active, vbat_bank,
                                            v_start, v_end, stop_ok);
    st->s_active = inv_gen_charge_soc_gate(st->s_active, soc,
                                           s_start, s_end, stop_ok);
    return charge_by_soc ? st->s_active : st->v_active;
}
