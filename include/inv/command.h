/*
 * HR 11 ResetSetting — the one-shot command register (docs/39 T12).
 *
 * HR 11 is not a stored setting: each bit triggers an ARM-side action, then the
 * register reads back 0 (the factory handles it flag-driven from its super-loop;
 * docs/23 §Reset-to-default, docs/wiring/ARM-UART5-dongle/HR011-ResetSetting.md).
 * This module decodes the command word and dispatches to caller-supplied ops, so
 * it is host-testable (mock ops) and wired to real actions from main.c.
 */
#ifndef INV_COMMAND_H
#define INV_COMMAND_H

#include <stdint.h>

/* HR 11 ResetSetting bits (Modbus spec / HR011 doc). */
enum {
    INV_CMD_ENERGY_CLR    = 1u << 0,  /* EnergyRecordClr: clear energy + runtime counters */
    INV_CMD_ALL_DEFAULT   = 1u << 1,  /* AlltoDefault: restore settings to defaults        */
    INV_CMD_ADJRATIO_CLR  = 1u << 2,  /* AdjRatioClr: correction coefficient -> 1          */
    INV_CMD_FAULT_CLR     = 1u << 3,  /* FaultRecordClr: clear fault record                */
    INV_CMD_MONITOR_CLR   = 1u << 4,  /* MonitorData: clear offline monitoring records     */
    INV_CMD_BMS_CHG_ON    = 1u << 5,  /* BMSChgSWOn: battery charge switch on               */
    INV_CMD_BMS_DISCHG_ON = 1u << 6,  /* BMSDischgSWOn: battery discharge switch on         */
    INV_CMD_INV_REBOOT    = 1u << 7,  /* InvReboot: restart the inverter                    */
};
#define INV_CMD_KNOWN_MASK  0x00FFu   /* bits 8-15 reserved */

/* Actions for each command bit. Any may be NULL (= not supported here, skipped).
 * reboot(), if present, is invoked LAST and is not expected to return. */
typedef struct {
    void (*energy_clear)(void);
    void (*restore_defaults)(void);
    void (*adjratio_clear)(void);
    void (*fault_clear)(void);
    void (*monitor_clear)(void);
    void (*bms_charge_on)(void);
    void (*bms_discharge_on)(void);
    void (*reboot)(void);
} inv_cmd_ops_t;

/* Execute an HR 11 ResetSetting word: invoke the op for each set, known bit
 * (skipping NULL ops and reserved bits). reboot is run last. Returns the mask of
 * bits actually acted on (set, known, non-NULL op). The command is one-shot —
 * the caller must NOT store HR 11 (it reads back 0). */
uint16_t inv_command_apply(uint16_t bits, const inv_cmd_ops_t *ops);

#endif /* INV_COMMAND_H */
