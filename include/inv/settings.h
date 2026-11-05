/*
 * User/installer settings model, reconstructed from the HMI menu strings in the
 * original "com" firmware. This is a clean-room data model: the field list is
 * derived from observed menu items, but types, ranges, defaults, units, scaling
 * and the on-flash storage layout are NOT yet recovered and are placeholders.
 *
 * STATUS: DRAFT / SPEC. Do not treat the struct layout as the real EEPROM/flash
 * format — that must be recovered separately (see docs/02-recovered-model.md).
 */
#ifndef INV_SETTINGS_H
#define INV_SETTINGS_H

#include <stdint.h>
#include <stdbool.h>

typedef enum { BAT_LEAD_ACID = 0, BAT_LITHIUM = 1 } inv_battery_type_t;

/* "According to Bat SOC" / "According to Bat Volt" / "According to time" */
typedef enum { CHG_BY_SOC = 0, CHG_BY_VOLT = 1, CHG_BY_TIME = 2 } inv_charge_basis_t;

/* Output voltage/standard options seen: 208/120, 220/110, 230/115,
 * 240/120, 200/100, 127/220 V */
typedef enum {
    OUT_208_120 = 0, OUT_220_110, OUT_230_115,
    OUT_240_120, OUT_200_100, OUT_127_220
} inv_output_standard_t;

/* CT sample ratio options seen: 1000:1, 2000:1, 3000:1 */
typedef enum { CT_1000_1 = 0, CT_2000_1, CT_3000_1 } inv_ct_ratio_t;

typedef struct {
    /* --- Battery --- */
    inv_battery_type_t battery_type;        /* "Battery Type"            */
    uint16_t  lithium_type;                 /* "Lithium Type"            */
    uint16_t  lead_acid_capacity_ah;        /* "Lead-acid Capacity"      */
    uint16_t  lead_acid_charge_mv;          /* "Lead-Acid Charge Voltage"   (scaling TBD) */
    uint16_t  lead_acid_float_mv;           /* "Lead-Acid Floating Voltage"               */
    bool      battery_eco_enable;           /* "Battery ECO Enable"      */
    bool      battery_wakeup;               /* "Battery Wake up"         */
    bool      battery_shared;               /* "Battery Shared"          */
    uint16_t  battery_warning_soc;          /* "Battery Warning SOC"     */
    uint16_t  battery_warning_mv;           /* "Battery Warning Volt"    */

    /* --- Charge / discharge --- */
    inv_charge_basis_t charge_basis;        /* "According to ..."        */
    uint16_t  charge_current_limit_a;       /* "Charge Current Limit"    */
    bool      discharge_control;            /* "Discharge Control"       */
    uint16_t  discharge_current_limit_a;    /* "Discharge Current Limit" */
    uint16_t  discharge_cutoff_soc;         /* "Discharge Cut-off SOC"   */
    uint16_t  discharge_cutoff_mv;          /* "Discharge Cut-off Volt"  */

    /* --- AC charge (charge battery from grid in a window) --- */
    bool      ac_charge_enable;
    uint16_t  ac_charge_current_a;          /* "AC Charge Battery Current" */
    uint16_t  ac_charge_soc;                /* "AC Charge Battery SOC"     */
    uint16_t  ac_charge_mv;                 /* "AC Charge Battery Voltage" */
    /* "AC Charge Time" / "Set Time" / "LED Timer" / "Soft Timer" -> time windows (TBD) */

    /* --- AC couple (coupling an external grid-tie PV inverter) --- */
    uint16_t  ac_couple_start_soc;          /* "AC Couple Start SOC"  */
    uint16_t  ac_couple_end_soc;            /* "AC Couple End SOC"    */
    uint16_t  ac_couple_start_mv;           /* "AC Couple Start Volt" */
    uint16_t  ac_couple_end_mv;             /* "AC Couple End Volt"   */

    /* --- Generator charge --- */
    uint16_t  gen_charge_type;              /* "Generator Charge Type"        */
    uint16_t  gen_charge_current_a;         /* "Gen Charge Bat Current"       */
    uint16_t  gen_charge_start_soc;         /* "Gen Charge Start Bat SOC"     */
    uint16_t  gen_charge_end_soc;           /* "Gen Charge End Bat SOC"       */
    uint16_t  gen_charge_start_mv;          /* "Gen Charge Start Bat Volt"    */
    uint16_t  gen_charge_end_mv;            /* "Gen Charge End Bat Volt"      */

    /* --- Grid / metering --- */
    bool      grid_always_on;               /* "Grid Always On"          */
    bool      export_to_grid;               /* "Export to Grid"          */
    bool      grid_ct_connection;           /* "Grid CT Connection"      */
    inv_ct_ratio_t ct_ratio;                /* "CT Sample Ratio"         */
    bool      ct_direction_reversed;        /* "CT Direction Reversed"   */
    bool      npe_connect_inner;            /* "N-PE Connect (Inner)"    */

    /* --- EPS (off-grid output) --- */
    uint16_t  eps_voltage_set;              /* "EPS Voltage Set"         */
    uint16_t  eps_frequency_set;            /* "EPS Frequency Set"       */
    inv_output_standard_t output_standard;  /* 208/120 .. 127/220        */

    /* --- Identity --- */
    uint16_t  model;                        /* "Model"                   */
} inv_settings_t;

#endif /* INV_SETTINGS_H */
