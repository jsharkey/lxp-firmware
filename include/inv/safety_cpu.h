/*
 * Safety-CPU telemetry (docs/29, docs/30, docs/33).
 *
 * The redundant / "safety" CPU streams the live grid/PV/bus measurements to the
 * ARM over USART2 as an EG4 "type-1" big-endian frame. The frame is decoded into
 * a telemetry bank laid out exactly like the factory's (docs/33): each field at a
 * fixed byte offset, native little-endian u16. `safety_cpu_publish()` copies that
 * bank into the Modbus input-register image, applying the EG4 scaling the factory
 * getter uses (verbatim for voltages/frequencies; inverter-current RMS x10;
 * radiator temperatures /10).
 *
 * Only the serve half (bank -> scaled input register) lives here; wiring the
 * USART2 byte stream into the bank is a separate driver (the factory's is DMA +
 * an RTOS task, docs/33).
 */
#ifndef INV_SAFETY_CPU_H
#define INV_SAFETY_CPU_H

#include <stdint.h>

#define SAFETY_BANK_SIZE 256u

/* Decoded safety-CPU telemetry, in the factory bank layout (docs/33). A USART2
 * frame parser fills this; the field offsets are the SAFETY_* constants below. */
extern uint8_t g_safety_bank[SAFETY_BANK_SIZE];

/* Byte offsets of each telemetry field within g_safety_bank (docs/33). */
enum {
    SAFETY_OFF_PV1      = 0x4c,
    SAFETY_OFF_PV2      = 0x4e,
    SAFETY_OFF_VAC_R    = 0x20,
    SAFETY_OFF_VAC_S    = 0x28,
    SAFETY_OFF_VAC_T    = 0xb6,
    SAFETY_OFF_FAC      = 0x5e,
    SAFETY_OFF_IINV     = 0x24,
    SAFETY_OFF_VEPS_R   = 0x22,
    SAFETY_OFF_FEPS     = 0x60,
    SAFETY_OFF_VBUS1    = 0x0e,
    SAFETY_OFF_VBUS2    = 0x10,
    SAFETY_OFF_VBUS_P   = 0x12,
    SAFETY_OFF_GEN_FREQ = 0x62,
    SAFETY_OFF_T_RAD1   = 0x1e,
    SAFETY_OFF_T_RAD2   = 0x1c
};

/* Publish the decoded telemetry into the Modbus input-register image
 * (`input_reg`, length `n`), applying the EG4 scaling. Safe to call every loop. */
void safety_cpu_publish(uint16_t *input_reg, uint16_t n);

#endif /* INV_SAFETY_CPU_H */
