/*
 * Operating / working modes — AUTHORITATIVE.
 *
 * Source: EG4 18kPV-12LV Modbus RTU Protocol, Table 9 ("Working modes
 * definition"). This is the value of input register 0 ("State").
 *
 * KEY INSIGHT: the mode is a BITMASK, not a dense enum. Each bit is an
 * independent condition; displayed modes are ORs of these bits. This matches
 * the HMI labels recovered from the binary (PVChargeGridOn = PV_CHARGE|PV_ONGRID,
 * etc.) and is the clean way to model the state machine.
 */
#ifndef INV_STATES_H
#define INV_STATES_H

#include <stdint.h>

/* Individual mode bits (as seen in the combined values of Table 9) */
enum {
    MODE_BIT_PV_ONGRID   = 0x04,  /* PV exporting to load/grid       */
    MODE_BIT_PV_CHARGE   = 0x08,  /* PV charging the battery         */
    MODE_BIT_BAT_ONGRID  = 0x10,  /* battery discharging, grid-tied  */
    MODE_BIT_AC_CHARGE   = 0x20,  /* grid charging the battery       */
    MODE_BIT_BAT_OFFGRID = 0x40,  /* battery feeding load, islanded  */
    MODE_BIT_PV_OFFGRID  = 0x80,  /* PV feeding load, islanded       */
};

/* Named composite values exactly as Table 9 lists them */
typedef enum {
    STATE_STANDBY            = 0x00,  /* Standby                                   */
    STATE_FAULT              = 0x01,  /* Inverter in fault status                  */
    STATE_PROGRAMMING        = 0x02,  /* Firmware update in progress               */
    STATE_PV_ONGRID          = 0x04,  /* PV on-grid (export to load & grid)        */
    STATE_PV_CHARGE          = 0x08,  /* PV charge                                 */
    STATE_PV_CHARGE_ONGRID   = 0x0C,  /* PV charge + on-grid                       */
    STATE_BAT_ONGRID         = 0x10,  /* Battery on-grid (discharge to load/grid)  */
    STATE_PV_BAT_ONGRID      = 0x14,  /* PV + battery on-grid                      */
    STATE_AC_CHARGE          = 0x20,  /* AC charge (grid -> battery)               */
    STATE_PV_AC_CHARGE       = 0x28,  /* PV + AC charge                            */
    STATE_BAT_OFFGRID        = 0x40,  /* Battery off-grid (EPS backup)             */
    STATE_PV_OFFGRID         = 0x80,  /* PV off-grid (not recommended alone)       */
    STATE_PV_BAT_OFFGRID     = 0xC0,  /* PV + battery off-grid                     */
    STATE_PV_CHARGE_OFFGRID  = 0x88   /* PV charge + off-grid                      */
} inv_state_t;

#endif /* INV_STATES_H */
