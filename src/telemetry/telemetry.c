/*
 * ARM-computed telemetry serve layer. See inv/telemetry.h and docs/39 T07.
 * Reproduces the factory serve scaling: powers 0.1 W -> IR = internal/10,
 * apparent power 1:1, RunningTime u32 split across IR 69/70.
 */
#include "inv/telemetry.h"
#include "inv/modbus_map.h"

#define TELEMETRY_RUN_STATE 3u   /* op_state >= this => running (matches energy/docs/22) */

uint16_t inv_power_to_ir(uint32_t internal_01w)
{
    return (uint16_t)(internal_01w / 10u);
}

void inv_telemetry_publish(uint16_t *ir, const inv_telemetry_t *t)
{
    ir[IR_PPV1]       = inv_power_to_ir(t->p_pv1);
    ir[IR_PPV2]       = inv_power_to_ir(t->p_pv2);
    ir[IR_PPV3]       = inv_power_to_ir(t->p_pv3);
    ir[IR_PCHARGE]    = inv_power_to_ir(t->p_charge);
    ir[IR_PDISCHARGE] = inv_power_to_ir(t->p_discharge);
    ir[IR_PINV]       = inv_power_to_ir(t->p_inv);
    ir[IR_PREC]       = inv_power_to_ir(t->p_rec);
    ir[IR_PEPS]       = inv_power_to_ir(t->p_eps);
    ir[IR_SEPS]       = t->s_eps;                      /* apparent power served 1:1 (VA) */
    ir[IR_PTOGRID]    = inv_power_to_ir(t->p_togrid);
    ir[IR_PTOUSER]    = inv_power_to_ir(t->p_touser);
    ir[IR_RUNTIME_L]  = (uint16_t)(t->runtime_s & 0xFFFF);
    ir[IR_RUNTIME_H]  = (uint16_t)(t->runtime_s >> 16);
}

void inv_telemetry_runtime_tick(inv_telemetry_t *t, uint8_t op_state)
{
    if (op_state >= TELEMETRY_RUN_STATE) t->runtime_s++;
}
