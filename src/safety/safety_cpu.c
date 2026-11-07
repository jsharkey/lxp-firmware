/*
 * Safety-CPU telemetry -> Modbus input registers (docs/29, docs/30, docs/33).
 * See include/inv/safety_cpu.h for the model.
 */
#include "inv/safety_cpu.h"
#include "inv/modbus_map.h"
#include "inv/variant.h"

uint8_t g_safety_bank[SAFETY_BANK_SIZE];

/* ASCII lowercase, locale-independent (the factory compare is case-insensitive,
 * sub_0801a93a). */
static char to_lower(char c)
{
    return (c >= 'A' && c <= 'Z') ? (char)(c + ('a' - 'A')) : c;
}

/* W008: does the relayed peer identity match the expected model code? A 4-char
 * case-insensitive compare (docs/32, docs/33 §tag-0; factory vs "ceaa"). A NULL or
 * short model_code never matches (-> W008 raised), which is the safe default. */
bool inv_fw_ident_matches(const uint8_t ident[SAFETY_IDENT_LEN], const char *model_code)
{
    if (!ident || !model_code)
        return false;
    for (unsigned i = 0; i < SAFETY_IDENT_LEN; i++) {
        if (model_code[i] == '\0')
            return false;  /* model_code shorter than 4 chars */
        if (to_lower((char)ident[i]) != to_lower(model_code[i]))
            return false;
    }
    return true;
}

uint8_t safety_cpu_dsp_version(void)
{
    return g_safety_bank[SAFETY_OFF_DSP_VER];
}

bool safety_cpu_fw_mismatch(void)
{
    /* Latched, like the factory's version-OK health bit (0x2000d890 bit 10,
     * T02b): W008 is present from boot until a matching peer identity is seen,
     * then stays cleared for the rest of the run. The relayed identity is constant
     * per boot on real hardware, so the latch is never observable mid-run -- it
     * only keeps a transient garbage frame during link bring-up from flapping W008
     * once the peer has identified itself. */
    static bool fw_ok;
    if (inv_fw_ident_matches(&g_safety_bank[SAFETY_OFF_IDENT], inv_variant()->model_code))
        fw_ok = true;
    return !fw_ok;
}

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

    /* Inverter-side battery voltage (IR 107) and power factor (IR 19): served
     * verbatim from the bank, matching the factory getter sweep (docs/33). PF is
     * the raw 0-2000 encoded value (IR019-PF.md); the ARM relays it, the client
     * decodes the range. */
    PUT(IR_BAT_VOLT_INV, bank_u16(SAFETY_OFF_BATV_INV));
    PUT(IR_PF,           bank_u16(SAFETY_OFF_PF));

#undef PUT
}
