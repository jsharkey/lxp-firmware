/* HR 11 ResetSetting command dispatcher — see inv/command.h. */
#include "inv/command.h"

static void run(void (*fn)(void), uint16_t bit, uint16_t *acted)
{
    if (fn) { fn(); *acted |= bit; }
}

uint16_t inv_command_apply(uint16_t bits, const inv_cmd_ops_t *ops)
{
    uint16_t acted = 0;
    if (!ops) return 0;
    if (bits & INV_CMD_ENERGY_CLR)    run(ops->energy_clear,     INV_CMD_ENERGY_CLR,    &acted);
    if (bits & INV_CMD_ALL_DEFAULT)   run(ops->restore_defaults, INV_CMD_ALL_DEFAULT,   &acted);
    if (bits & INV_CMD_ADJRATIO_CLR)  run(ops->adjratio_clear,   INV_CMD_ADJRATIO_CLR,  &acted);
    if (bits & INV_CMD_FAULT_CLR)     run(ops->fault_clear,      INV_CMD_FAULT_CLR,     &acted);
    if (bits & INV_CMD_MONITOR_CLR)   run(ops->monitor_clear,    INV_CMD_MONITOR_CLR,   &acted);
    if (bits & INV_CMD_BMS_CHG_ON)    run(ops->bms_charge_on,    INV_CMD_BMS_CHG_ON,    &acted);
    if (bits & INV_CMD_BMS_DISCHG_ON) run(ops->bms_discharge_on, INV_CMD_BMS_DISCHG_ON, &acted);
    if (bits & INV_CMD_INV_REBOOT)    run(ops->reboot,           INV_CMD_INV_REBOOT,    &acted); /* last */
    return acted;
}
