/*
 * Battery working-limit derivation (BMS 0x351 + settings -> served/pushed limits).
 *
 * The inverter does not forward the pack's raw 0x351 limits untouched: it serves
 * a *working* charge-voltage reference that is the lesser of the BMS-reported
 * limit and the user's ChargeVoltRef setting (HR 99). This is what reaches the
 * dongle at IR 83 and what feeds the DSP config push (block 1).
 *
 * Oracle (factory, docs/39 T11a, docs/wiring/ARM-CAN1-BMS.md): black-box on the
 * ceaa-07xx image, IR 83 = min(0x351 charge-V, HR 99) across the whole range
 * (chgV 0/100/560/600/1000 vs HR 99 520/574/590 all match min()). The "~57.4 V"
 * mentioned in the old on_can_frame comment is simply HR 99's factory power-on
 * default (574 = 57.4 V), NOT a cell-count-derived clamp: writing HR 99 = 590
 * raises the ceiling to 590, so there is no separate hard clamp.
 *
 * Pure function: inputs in, value out, no globals -- host-, micro- and
 * firmware-callable (docs/35, docs/39 "How to work a task").
 */
#ifndef INV_BMS_LIMITS_H
#define INV_BMS_LIMITS_H

#include <stdint.h>

/*
 * Working charge-voltage reference (0.1 V) the inverter serves at IR 83.
 *   bms_charge_volt_dv     -- the pack's 0x351 charge voltage limit (0.1 V)
 *   setting_charge_volt_dv -- HR 99 ChargeVoltRef (0.1 V)
 * Returns min(bms, setting): whichever is lower bounds the charge.
 */
uint16_t inv_bms_charge_volt_ref(uint16_t bms_charge_volt_dv,
                                 uint16_t setting_charge_volt_dv);

#endif /* INV_BMS_LIMITS_H */
