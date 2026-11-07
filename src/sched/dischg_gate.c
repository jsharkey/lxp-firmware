/*
 * Discharge-control voltage gate with hysteresis. See include/inv/dischg_gate.h
 * and docs/41-charge-discharge-schedule-gates.md (T15). Mirrors the factory
 * evaluator sub_0801ed28's voltage path, byte-for-byte on the decision:
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
