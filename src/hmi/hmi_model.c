/*
 * HMI menu model — the reimplementation's menu tree.
 *
 * REPRESENTATIVE subset (not all 96 items yet): it exercises every item kind
 * (INFO / U16 / ENUM / SUBMENU / ACTION) and nesting, with real labels and
 * register bindings + ranges from the EG4 protocol doc. Extend it to the full
 * menu using reference/string_catalog.txt (labels, in order) and
 * include/inv/modbus_map.h (registers + ranges). Mirrors the stock firmware's
 * data-driven menu table (docs/06-hmi.md).
 */
#include "inv/hmi.h"
#include "inv/modbus_map.h"

/* ---- enum choice lists ---- */
static const char *const ch_eps_volt[] = { "208V", "230V", "240V", "277V" };
static const char *const ch_eps_freq[] = { "50Hz", "60Hz" };
static const char *const ch_out_prio[] = { "Bat First", "PV First", "AC First" };
static const char *const ch_line_mode[] = { "APL", "UPS", "GEN" };
static const char *const ch_sys_type[]  = { "Single", "1ph Para M", "Slave", "3ph Para M" };
static const char *const ch_phase[]      = { "-", "R", "S", "T" };

static void act_restore_defaults(void); /* fwd */

/* ---- Generator-charge submenu ---- */
static const hmi_item_t gen_items[] = {
 {"Start Volt: ", HMI_U16, HMI_REG_HOLDING, HR_GEN_CHG_START_V, 384, 520, 1, 10, "V", 0,0, 0,0},
 {"End Volt: ",   HMI_U16, HMI_REG_HOLDING, HR_GEN_CHG_END_V,   480, 590, 1, 10, "V", 0,0, 0,0},
 {"Start SOC: ",  HMI_U16, HMI_REG_HOLDING, HR_GEN_CHG_START_SOC, 0,  90, 1,  1, "%", 0,0, 0,0},
 {"End SOC: ",    HMI_U16, HMI_REG_HOLDING, HR_GEN_CHG_END_SOC,  20, 100, 1,  1, "%", 0,0, 0,0},
 {"Max Curr: ",   HMI_U16, HMI_REG_HOLDING, HR_MAX_GEN_CHG_CURR,  0,  60, 1,  1, "A", 0,0, 0,0},
};
static const hmi_menu_t gen_menu = { "Gen Charge", gen_items, 5 };

/* ---- Parallel-setting submenu ---- */
static const hmi_item_t para_items[] = {
 {"Set System Type: ", HMI_ENUM, HMI_REG_HOLDING, HR_SET_SYSTEM_TYPE, 0,3,1,1,0, ch_sys_type, 4, 0,0},
 {"Set Composed Phase: ", HMI_ENUM, HMI_REG_HOLDING, HR_SET_COMPOSED_PH, 0,3,1,1,0, ch_phase, 4, 0,0},
};
static const hmi_menu_t para_menu = { "Parallel Setting", para_items, 2 };

/* ---- Root menu ---- */
static const hmi_item_t root_items[] = {
 /* live info */
 {"State: ",       HMI_INFO, HMI_REG_INPUT, IR_STATE, 0,0,0, 1,  0, 0,0, 0,0},
 {"Battery Volt: ",HMI_INFO, HMI_REG_INPUT, IR_VBAT,  0,0,0, 10,"V", 0,0, 0,0},
 {"SOC: ",         HMI_INFO, HMI_REG_INPUT, IR_SOC_SOH,0,0,0, 1, "%", 0,0, 0,0},
 {"Grid Freq: ",   HMI_INFO, HMI_REG_INPUT, IR_FAC,   0,0,0,100,"Hz", 0,0, 0,0},
 /* editable settings */
 {"EPS Voltage Set: ",  HMI_ENUM, HMI_REG_HOLDING, HR_EPS_VOLT_SET, 0,3,1,1,0, ch_eps_volt, 4, 0,0},
 {"EPS Frequency Set: ",HMI_ENUM, HMI_REG_HOLDING, HR_EPS_FREQ_SET, 0,1,1,1,0, ch_eps_freq, 2, 0,0},
 {"Output Prio: ",      HMI_ENUM, HMI_REG_HOLDING, HR_OUTPUT_PRIO_CFG,0,2,1,1,0, ch_out_prio,3, 0,0},
 {"Line Mode: ",        HMI_ENUM, HMI_REG_HOLDING, HR_LINE_MODE, 0,2,1,1,0, ch_line_mode,3, 0,0},
 {"Charge Current Limit: ",    HMI_U16, HMI_REG_HOLDING, HR_CHARGE_CURR, 0,140,1,1,"A", 0,0, 0,0},
 {"Discharge Current Limit: ", HMI_U16, HMI_REG_HOLDING, HR_DISCHG_CURR, 0,140,1,1,"A", 0,0, 0,0},
 {"Charge Voltage: ", HMI_U16, HMI_REG_HOLDING, HR_CHARGE_VOLT_REF, 500,590,1,10,"V", 0,0, 0,0},
 {"Discharge Cut-off SOC : ", HMI_U16, HMI_REG_HOLDING, HR_EOD, 10,90,1,1,"%", 0,0, 0,0},
 /* submenus + action */
 {"Parallel Setting ", HMI_SUBMENU, HMI_REG_NONE, 0, 0,0,0,0,0, 0,0, &para_menu, 0},
 {"Gen Charge ",       HMI_SUBMENU, HMI_REG_NONE, 0, 0,0,0,0,0, 0,0, &gen_menu, 0},
 {"Restore Defaults ", HMI_ACTION,  HMI_REG_NONE, 0, 0,0,0,0,0, 0,0, 0, act_restore_defaults},
};
const hmi_menu_t hmi_root_menu = { "Main", root_items, 15 };

/* ACTION: request "restore defaults" via the reset-setting holding register.
 * Wired weakly so firmware/tests can observe it; real persistence is TODO. */
__attribute__((weak)) void hmi_request_restore_defaults(void) { }
static void act_restore_defaults(void) { hmi_request_restore_defaults(); }
