/*
 * Fault and Warning codes — AUTHORITATIVE.
 *
 * Source: EG4 18kPV-12LV Modbus RTU Protocol, Table 10 ("Fault code and
 * warning code definition"). These are the exact bit positions of the two
 * 32-bit bitfields exposed over Modbus:
 *     FaultCode   = input registers 60 (low word) + 61 (high word)
 *     WarningCode = input registers 62 (low word) + 63 (high word)
 * The firmware reports faults as "E0NN" and warnings as "W0NN" where NN is the
 * bit index. A set bit = that condition active.
 *
 * NOTE: the on-screen HMI strings recovered from the binary mix both tables
 * (e.g. "BatVoltHigh" is WARNING W025, not a fault). Use these enums as the
 * single source of truth and treat the raw HMI strings as display labels.
 */
#ifndef INV_FAULTS_H
#define INV_FAULTS_H

#include <stdint.h>

/* ---- Faults: bit index in the 32-bit FaultCode field (regs 60/61) -------- */
typedef enum {
    FAULT_INTERNAL_COMM_1       = 0,   /* E000 Internal communication fault 1       */
    FAULT_MODEL                 = 1,   /* E001 Model fault                          */
    /* bits 2..7 reserved */
    FAULT_PARALLEL_CAN_LOST     = 8,   /* E008 Paralleling CAN communication lost   */
    FAULT_PARALLEL_MASTER_LOST  = 9,   /* E009 Master unit lost in paralleling sys  */
    FAULT_PARALLEL_MULTI_MASTER = 10,  /* E010 Multiple master units in parallel    */
    FAULT_PARALLEL_AC_INCONSIST = 11,  /* E011 AC input inconsistent in parallel    */
    FAULT_UPS_SHORT             = 12,  /* E012 UPS (EPS) short                      */
    FAULT_UPS_REVERSE_CURRENT   = 13,  /* E013 Reverse current on UPS output        */
    FAULT_BUS_SHORT             = 14,  /* E014 BUS short                            */
    FAULT_PARALLEL_PHASE_INCON  = 15,  /* E015 Grid phases inconsistent (3ph parall)*/
    FAULT_RELAY_CHECK           = 16,  /* E016 Relay check fault                    */
    FAULT_INTERNAL_COMM_2       = 17,  /* E017 Internal communication fault 2       */
    FAULT_INTERNAL_COMM_3       = 18,  /* E018 Internal communication fault 3       */
    FAULT_BUS_VOLT_HIGH         = 19,  /* E019 BUS voltage high                     */
    FAULT_EPS_CONNECT           = 20,  /* E020 EPS connection fault                 */
    FAULT_PV_VOLT_HIGH          = 21,  /* E021 PV voltage high                      */
    FAULT_OVER_CURRENT          = 22,  /* E022 Over-current protection (deprecated)  */
    FAULT_NEUTRAL               = 23,  /* E023 Neutral fault                        */
    FAULT_PV_SHORT              = 24,  /* E024 PV short                             */
    FAULT_RADIATOR_TEMP         = 25,  /* E025 Radiator temperature out of range    */
    FAULT_INTERNAL              = 26,  /* E026 Internal fault                       */
    FAULT_CPU_SAMPLE_MISMATCH   = 27,  /* E027 Main vs redundant CPU sample mismatch*/
    FAULT_INTERNAL_COMM_4       = 31   /* E031 Internal communication fault 4       */
} inv_fault_bit_t;

/* ---- Warnings: bit index in the 32-bit WarningCode field (regs 62/63) ---- */
typedef enum {
    WARN_BAT_COMM_FAIL          = 0,   /* W000 Battery communication failure        */
    WARN_AFCI_COMM_FAIL         = 1,   /* W001 AFCI communication failure           */
    WARN_AFCI_HIGH              = 2,   /* W002 AFCI high (arc fault)                */
    WARN_METER_COMM_FAIL        = 3,   /* W003 Meter communication failure          */
    WARN_BAT_CHG_DISCHG_FORBID  = 4,   /* W004 Charge & discharge forbidden by BMS  */
    WARN_AUTO_TEST_FAIL         = 5,   /* W005 Auto test failed                     */
    WARN_LCD_COMM_FAIL          = 7,   /* W007 LCD communication failure            */
    WARN_FW_VERSION_MISMATCH    = 8,   /* W008 Firmware version mismatch            */
    WARN_FAN_STUCK              = 9,   /* W009 Fan stuck                            */
    WARN_PARALLEL_NUM_RANGE     = 11,  /* W011 Parallel number out of range         */
    WARN_BAT_REVERSE            = 15,  /* W015 Battery reverse connection           */
    WARN_GRID_OUTAGE            = 16,  /* W016 Grid power outage                    */
    WARN_GRID_VOLT_RANGE        = 17,  /* W017 Grid voltage out of range            */
    WARN_GRID_FREQ_RANGE        = 18,  /* W018 Grid frequency out of range          */
    WARN_PV_INSULATION_LOW      = 20,  /* W020 PV insulation low                    */
    WARN_LEAKAGE_CURRENT_HIGH   = 21,  /* W021 Leakage current high                 */
    WARN_DCI_HIGH               = 22,  /* W022 DCI high                             */
    WARN_PV_SHORT               = 23,  /* W023 PV short                             */
    WARN_BAT_VOLT_HIGH          = 25,  /* W025 Battery voltage high                 */
    WARN_BAT_VOLT_LOW           = 26,  /* W026 Battery voltage low                  */
    WARN_BAT_OPEN_CIRCUIT       = 27,  /* W027 Battery open circuit                 */
    WARN_EPS_OVERLOAD           = 28,  /* W028 EPS overload                         */
    WARN_EPS_VOLT_HIGH          = 29,  /* W029 EPS voltage high                     */
    WARN_METER_REVERSE          = 30,  /* W030 Meter reverse connection             */
    WARN_DCV_HIGH               = 31   /* W031 DCV high                             */
} inv_warn_bit_t;

static inline int inv_fault_active(uint32_t faultcode, inv_fault_bit_t b)
{ return (faultcode >> (uint32_t)b) & 1u; }
static inline int inv_warn_active(uint32_t warncode, inv_warn_bit_t b)
{ return (warncode >> (uint32_t)b) & 1u; }

#endif /* INV_FAULTS_H */
