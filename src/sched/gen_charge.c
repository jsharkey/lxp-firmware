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
