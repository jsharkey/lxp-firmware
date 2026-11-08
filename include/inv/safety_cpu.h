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
#include <stdbool.h>

#define SAFETY_BANK_SIZE 256u

/* Decoded safety-CPU telemetry, in the factory bank layout (docs/33). A USART2
 * frame parser fills this; the field offsets are the SAFETY_* constants below. */
extern uint8_t g_safety_bank[SAFETY_BANK_SIZE];

/* Byte offsets of each telemetry field within g_safety_bank (docs/33). */
enum {
    /* Header / identity (tag-0, docs/33 §"Mode / identity / status"):
     *   +0x02      Control-CPU (DSP) FW version  -> HR 10 low (docs/32)
     *   +0x03..06  peer identity bytes           -> W008 compare (vs model_code) */
    SAFETY_OFF_DSP_VER   = 0x02,
    SAFETY_OFF_IDENT     = 0x03,  /* 4 bytes */
    SAFETY_IDENT_LEN     = 4,

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
    SAFETY_OFF_T_RAD2   = 0x1c,
    SAFETY_OFF_BATV_INV = 0x0a,   /* IR 107 inverter-side battery voltage (0.1 V) */
    SAFETY_OFF_PF       = 0xaa,   /* IR 19 power factor (0.001, encoded 0-2000)   */
    SAFETY_OFF_EPS_L1N  = 0x30,   /* IR 127 EPS output voltage L1-N (0.1 V)       */
    SAFETY_OFF_EPS_L2N  = 0x32,   /* IR 128 EPS output voltage L2-N (0.1 V)       */
    SAFETY_OFF_INT_FAULT= 0xc8    /* IR 6 internal DTC (safety-bank word)          */
};

/* Publish the decoded telemetry into the Modbus input-register image
 * (`input_reg`, length `n`), applying the EG4 scaling. Safe to call every loop. */
void safety_cpu_publish(uint16_t *input_reg, uint16_t n);

/* Control-CPU (DSP) firmware version the safety CPU relays at bank+2 (docs/32).
 * This is HR 10's low byte; HR 10 high is our own FW-version code. */
uint8_t safety_cpu_dsp_version(void);

/* inv_fw_ident_matches: the stateless 4-char case-insensitive identity compare the
 * factory classifier does (sub_0801a93a vs "ceaa"; T02b). Returns true when the
 * relayed identity matches the model code. A NULL/short model_code never matches.
 * `model_code` is the expected 4-char identity (normally inv_variant()->model_code). */
bool inv_fw_ident_matches(const uint8_t ident[SAFETY_IDENT_LEN], const char *model_code);

/* W008 (FW-version mismatch): true while ours should raise W008. It is LATCHED like
 * the factory's version-OK health bit (0x2000d890 bit 10): present from boot (bare
 * bank, no safety link yet) until a matching peer identity is relayed, then cleared
 * for the rest of the run. (The peer identity is constant per boot on hardware, so
 * the latch is only observable across boots -- it keeps a bring-up garbage frame
 * from flapping W008.) Stateful: reads the live g_safety_bank identity. */
bool safety_cpu_fw_mismatch(void);

#endif /* INV_SAFETY_CPU_H */
