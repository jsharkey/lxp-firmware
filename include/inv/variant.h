/*
 * Product-variant abstraction for the shared EG4 com-MCU codebase.
 *
 * The original "com" firmware is ONE codebase that ships on several EG4 all-in-one
 * inverters, variant-selected by the "Model" setting. Reverse-engineering three of
 * the factory ARM images proves this directly (see docs/10-18kpv-vs-12000xp.md
 * and docs/12-6000xp.md):
 *
 *   - EG4 12000XP  (05-series "..._ceaa-05xx_com_vE_250325.hex"; the current
 *                   reference is the 07-series "..._ceaa-07xx_vE_260214...hex" --
 *                   see docs/11-12000xp-revisions.md for the 05->07 delta)
 *   - EG4 18kPV    (image "..._FAAB-1Bxx_20240528_App.hex")
 *   - EG4 6000XP   (image "..._ccaa-xx15xx_260519.hex")
 *
 * Both run the SAME MCU (STM32F103 high-density, Cortex-M3), the SAME CMSIS-F1
 * SystemInit, and the SAME Keil-armcc scatter-loaded C runtime. They differ in a
 * small, enumerable set of ways: the flash/partition layout (monolithic image vs
 * bootloader + relocated "App"), the number of MPPTs (2 vs 3), whether the unit
 * is a grid-tie "hybrid", and the handful of features that implies.
 *
 * This header captures those deltas as DATA (an inv_variant_t descriptor) so the
 * rest of the firmware is written once and branches on the descriptor instead of
 * on #ifdefs sprinkled through the code. The ACTIVE variant is chosen at build
 * time (INV_VARIANT_18KPV / default 12000XP), but every variant's descriptor is
 * always linked in and queryable, which keeps host unit tests able to exercise
 * both, and leaves the door open to runtime selection by the Model register.
 *
 * STATUS: the structural facts (MCU, memory map, vector address, model/signature
 * markers, MPPT count, hybrid flag) are DIRECT READS from the two images. The
 * finer feature flags are derived from the Modbus superset + recovered HMI
 * strings and are marked where they are an inference rather than a direct read.
 */
#ifndef INV_VARIANT_H
#define INV_VARIANT_H

#include <stdint.h>
#include <stdbool.h>

/* ----- model identity ----------------------------------------------------- */
typedef enum {
    INV_MODEL_12000XP = 0,   /* non-hybrid, 2 MPPT, split-phase 120/240       */
    INV_MODEL_18KPV   = 1,   /* hybrid grid-tie, 3 MPPT, split-phase          */
    INV_MODEL_6000XP  = 2,    /* non-hybrid, 2 MPPT, split-phase (smaller sib) */
    INV_MODEL__COUNT
} inv_model_id_t;

/* Flash partitioning style recovered from the vector-table location. */
typedef enum {
    INV_IMAGE_MONOLITHIC = 0, /* vectors at flash base; single image (12000XP) */
    INV_IMAGE_APP_OVER_BL = 1  /* bootloader low, App vectors relocated (18kPV) */
} inv_image_layout_t;

/*
 * A single product variant. Everything here is used to specialise behaviour
 * without #ifdefs: clock/VTOR bring-up, the Modbus register surface, the DSP
 * config push, and HMI gating all read these fields.
 */
typedef struct {
    inv_model_id_t id;
    const char    *name;        /* human name, e.g. "EG4 18kPV"                */
    const char    *model_code;  /* 4-char factory code in the image ("FAAB")   */
    const char    *image_sig;   /* top-of-image signature word ("SNEC"/"EAA1") */

    /* --- power topology (the hardware deltas the user called out) --- */
    uint8_t  mppt_count;        /* independent PV trackers: 2 (12K) or 3 (18k) */
    uint8_t  phase_count;       /* AC output phases (1 = split-phase 120/240)  */
    bool     hybrid;            /* true = grid-interactive hybrid (18kPV)      */

    /* --- feature gates derived from topology (see notes in variant.c) --- */
    bool     feat_export_to_grid; /* sell/feed-in to grid   (hybrid only)      */
    bool     feat_ac_couple;      /* couple an external GT PV inverter         */
    bool     feat_generator_port; /* dedicated generator AC input + gen-charge */

    /* --- memory / boot layout (direct reads from the vector tables) --- */
    inv_image_layout_t layout;
    uint32_t flash_base;        /* 0x08000000 on both (STM32 flash alias)      */
    uint32_t flash_size;        /* physical part size in bytes                 */
    uint32_t bootloader_size;   /* bytes reserved below the App (0 if mono)    */
    uint32_t vector_addr;       /* address the App's vector table lives at,
                                   and the value written to SCB->VTOR          */
    uint32_t sram_size;         /* SRAM size in bytes                          */
} inv_variant_t;

/* Descriptor for a given model (always available; never NULL for a valid id). */
const inv_variant_t *inv_variant_by_model(inv_model_id_t id);

/*
 * The variant this firmware was BUILT for. Selected at compile time:
 *   -DINV_VARIANT_18KPV  -> 18kPV
 *   (default)            -> 12000XP
 * Returned pointer is to a const descriptor in flash; safe to call from
 * SystemInit() before the C library / RAM are fully up.
 */
const inv_variant_t *inv_variant(void);

/* ----- convenience predicates (read the active variant) ------------------- */
static inline bool inv_has_mppt3(void)   { return inv_variant()->mppt_count >= 3; }
static inline bool inv_is_hybrid(void)   { return inv_variant()->hybrid; }

/*
 * Is a Modbus INPUT register meaningful on the active variant?
 * The 18kPV Modbus map is a SUPERSET; on the 2-MPPT 12000XP the 3rd-tracker
 * registers (Vpv3/Ppv3/Epv3*) carry no data. Telemetry producers and the DSP
 * push use this so a 12000XP build never fabricates PV3 values, while a Modbus
 * master still gets a well-formed 0 if it polls them.
 */
bool inv_ir_active(uint16_t input_reg);

#endif /* INV_VARIANT_H */
