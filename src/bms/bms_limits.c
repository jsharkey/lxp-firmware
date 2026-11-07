/*
 * Battery working-limit derivation -- transport-agnostic, host-testable.
 * See include/inv/bms_limits.h and docs/39 T11a / docs/wiring/ARM-CAN1-BMS.md.
 */
#include "inv/bms_limits.h"

uint16_t inv_bms_charge_volt_ref(uint16_t bms_charge_volt_dv,
                                 uint16_t setting_charge_volt_dv)
{
    /* The lower of the pack's reported limit and the ChargeVoltRef setting
     * bounds the charge voltage (factory: IR 83 = min(0x351 chg-V, HR 99)). */
    return bms_charge_volt_dv < setting_charge_volt_dv
         ? bms_charge_volt_dv
         : setting_charge_volt_dv;
}
