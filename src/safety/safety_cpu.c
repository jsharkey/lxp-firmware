/*
 * Safety-CPU telemetry -> Modbus input registers (docs/29, docs/30, docs/33).
 * See include/inv/safety_cpu.h for the model.
 */
#include "inv/safety_cpu.h"
#include "inv/modbus_map.h"

uint8_t g_safety_bank[SAFETY_BANK_SIZE];

/* Read a native little-endian u16 field from the bank (as the USART2 parser
 * stores it). Signed variant for temperatures. */
static uint16_t bank_u16(uint16_t off)
{
    return (uint16_t)(g_safety_bank[off] | ((uint16_t)g_safety_bank[off + 1] << 8));
}
static int16_t bank_s16(uint16_t off)
{
    return (int16_t)bank_u16(off);
}

void safety_cpu_publish(uint16_t *input_reg, uint16_t n)
{
    if (!input_reg)
        return;

#define PUT(ir, val) do { if ((ir) < n) input_reg[(ir)] = (uint16_t)(val); } while (0)

    /* Voltages / frequencies: served verbatim (0.1 V, 0.01 Hz). */
    PUT(IR_VPV1,  bank_u16(SAFETY_OFF_PV1));
    PUT(IR_VPV2,  bank_u16(SAFETY_OFF_PV2));
    PUT(IR_VAC_R, bank_u16(SAFETY_OFF_VAC_R));
    PUT(IR_VAC_S, bank_u16(SAFETY_OFF_VAC_S));
    PUT(IR_VAC_T, bank_u16(SAFETY_OFF_VAC_T));
    PUT(IR_FAC,   bank_u16(SAFETY_OFF_FAC));
    PUT(IR_VEPS_R, bank_u16(SAFETY_OFF_VEPS_R));
    PUT(IR_FEPS,  bank_u16(SAFETY_OFF_FEPS));
    PUT(IR_VBUS1, bank_u16(SAFETY_OFF_VBUS1));
    PUT(IR_VBUS2, bank_u16(SAFETY_OFF_VBUS2));
    PUT(IR_VBUS_P, bank_u16(SAFETY_OFF_VBUS_P));
    PUT(IR_GEN_FREQ, bank_u16(SAFETY_OFF_GEN_FREQ));

    /* Inverter current RMS: the factory getter scales the bank field x10. */
    PUT(IR_IINV_RMS, (uint16_t)(bank_u16(SAFETY_OFF_IINV) * 10u));

    /* Radiator temperatures: served /10 (bank is 0.1 degC, register is 1 degC),
     * signed. */
    PUT(IR_T_RADIATOR1, (uint16_t)(bank_s16(SAFETY_OFF_T_RAD1) / 10));
    PUT(IR_T_RADIATOR2, (uint16_t)(bank_s16(SAFETY_OFF_T_RAD2) / 10));

#undef PUT
}
