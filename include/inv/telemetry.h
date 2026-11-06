/*
 * ARM-computed telemetry input registers (docs/39 T07, docs/22, docs/33 §3).
 *
 * A set of dongle input registers are NOT relayed from a peer bank but COMPUTED
 * by the ARM (PV power = V*I, the battery-power sign split, inverter/EPS/grid
 * powers, apparent power, running time) and served with a fixed scaling. The
 * factory keeps the powers internally in 0.1 W and the input getter serves
 * IR = internal / 10 (recovered by oracle -- NOT a float, correcting the roadmap
 * guess). Apparent power (Seps) is served 1:1 in VA. RunningTime is a u32 seconds
 * counter served as a low/high register pair.
 *
 * The upstream compute (V*I, the sign split) is fed by the DSP/safety-CPU links
 * (parser sub_08025ab8), which are not yet wired in the harness -- so the internal
 * quantities here are injected until T05/T09 land. This module is the clean-room
 * SERVE layer: internal computed quantities -> served input registers.
 */
#ifndef INV_TELEMETRY_H
#define INV_TELEMETRY_H

#include <stdint.h>

/* The ARM's computed quantities, in the factory's internal units. */
typedef struct {
    uint32_t p_pv1, p_pv2, p_pv3;     /* PV power, 0.1 W                     */
    uint32_t p_charge, p_discharge;   /* battery power sign-split, 0.1 W each (>=0) */
    uint32_t p_inv, p_rec;            /* inverter / rectifier power, 0.1 W   */
    uint32_t p_eps;                   /* EPS active power, 0.1 W             */
    uint16_t s_eps;                   /* EPS apparent power, 1 VA (served 1:1)*/
    uint32_t p_togrid, p_touser;      /* export / import power, 0.1 W        */
    uint32_t runtime_s;               /* running time, seconds               */
} inv_telemetry_t;

/* Serve one 0.1 W power as the factory does: IR = (uint16_t)(internal / 10). */
uint16_t inv_power_to_ir(uint32_t internal_01w);

/* Publish all computed quantities into a Modbus input-register image
 * (>= 71 entries): powers scaled /10, Seps 1:1, RunningTime as IR 69/70. */
void inv_telemetry_publish(uint16_t *input_reg, const inv_telemetry_t *t);

/* Advance the running-time counter one second, gated on a running operating
 * state (IR_STATE >= running threshold), matching the factory counter. */
void inv_telemetry_runtime_tick(inv_telemetry_t *t, uint8_t op_state);

#endif /* INV_TELEMETRY_H */
