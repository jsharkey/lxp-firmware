/*
 * Discharge-control voltage gate with hysteresis. See include/inv/dischg_gate.h
 * and docs/41-charge-discharge-schedule-gates.md (T15). Mirrors the factory
 * discharge-gate voltage path byte-for-byte on the decision (07 block
 * 0x080355c2; 05 sub_0801ed28):
 *   v = (uint16 bank voltage) / 10 (signed);  active = active ? v>=stop : v>=start
 */
#include "inv/dischg_gate.h"

bool inv_dischg_volt_gate(bool active, uint16_t vbat_bank,
                          uint16_t start_v, uint16_t stop_v)
{
    /* The factory zero-extends the bank word (ldrh) then signed-divides by 10
     * (sdiv) and does signed compares (blt/bge); reproduce that exactly. */
    int32_t v = (int32_t)(uint16_t)vbat_bank / 10;

    if (active)
        return v >= (int32_t)stop_v;    /* stay on until V drops below stop */
    return v >= (int32_t)start_v;       /* turn on once V reaches start     */
}

bool inv_dischg_soc_gate(bool active, uint8_t soc,
                         uint8_t start_soc, uint8_t stop_soc)
{
    /* The SOC sibling (07 block 0x08035616, verdict 0x2000dbc4): the factory reads
     * the SOC byte and the two 1-byte thresholds and compares UNSIGNED (blo/bhs) --
     * same latched hysteresis as the voltage gate. */
    if (active)
        return soc >= stop_soc;         /* stay on until SOC drops below stop */
    return soc >= start_soc;            /* turn on once SOC reaches start      */
}

bool inv_dischg_permit(inv_dischg_state_t *st, uint8_t ctrl_type,
                       uint16_t vbat_bank, uint16_t v_start, uint16_t v_stop,
                       uint8_t soc, uint8_t s_start, uint8_t s_stop)
{
    /* Step both gates every call so neither latch goes stale across a mode change. */
    st->v_active = inv_dischg_volt_gate(st->v_active, vbat_bank, v_start, v_stop);
    st->s_active = inv_dischg_soc_gate(st->s_active, soc, s_start, s_stop);

    switch (ctrl_type & 0x3u) {
    case 1:  return st->s_active;                      /* by SOC     */
    case 2:  return st->v_active && st->s_active;      /* both (ours' AND) */
    case 0:
    default: return st->v_active;                      /* by voltage */
    }
}
