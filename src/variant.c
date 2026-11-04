/*
 * Product-variant descriptors. See include/inv/variant.h and
 * docs/09-18kpv-vs-12000xp.md for how each field was recovered.
 *
 * All structural fields below are DIRECT READS from the two factory images:
 *
 *   field            12000XP (ceaa / "SNEC")      18kPV App (FAAB / "EAA1")
 *   ---------------  ---------------------------  ----------------------------
 *   layout           monolithic                   App over bootloader
 *   vector_addr      0x08000000                   0x0800C800
 *   bootloader_size  0                            0xC800  (51,200 B)
 *   initial MSP      0x200008D0                   0x20000478
 *   reset handler    0x08002980                   0x0802B788
 *   top-of-image sig "SNEC" @0x0807F7FC           "EAA1" @0x0803F7FC
 *
 * The 12000XP image fills a 512 KB part (top marker at 0x0807F7FC); the 18kPV
 * App occupies a 256 KB App region above its bootloader (top marker 0x0803F7FC).
 *
 * The topology fields (mppt_count, hybrid, phase_count) come from the hardware
 * (maintainer-confirmed: 18kPV is a 3-MPPT hybrid, 12000XP a 2-MPPT non-hybrid)
 * and are corroborated by the recovered HMI strings ("Same for 2 MPPTs",
 * "PV1,PV2,independent" in the 12000XP) and by the Modbus superset's Vpv3/Ppv3.
 *
 * The feat_* flags are an INFERENCE from topology + the Modbus map, not a direct
 * read of a per-model gate inside the image; they are the project's current
 * best model and should be refined as the variant-selection logic is decoded.
 */
#include "inv/variant.h"

static const inv_variant_t k_variants[INV_MODEL__COUNT] = {
    [INV_MODEL_12000XP] = {
        .id          = INV_MODEL_12000XP,
        .name        = "EG4 12000XP",
        .model_code  = "ceaa",
        .image_sig   = "SNEC",

        .mppt_count  = 2,
        .phase_count = 1,            /* split-phase 120/240 V               */
        .hybrid      = false,

        .feat_export_to_grid = false, /* non-hybrid: no sell-to-grid        */
        .feat_ac_couple      = false, /* menu string present but inactive    */
        .feat_generator_port = true,  /* has generator input + gen-charge    */

        .layout          = INV_IMAGE_MONOLITHIC,
        .flash_base      = 0x08000000UL,
        .flash_size      = 512U * 1024U,
        .bootloader_size = 0U,
        .vector_addr     = 0x08000000UL,
        .sram_size       = 64U * 1024U,
    },
    [INV_MODEL_18KPV] = {
        .id          = INV_MODEL_18KPV,
        .name        = "EG4 18kPV",
        .model_code  = "FAAB",
        .image_sig   = "EAA1",

        .mppt_count  = 3,
        .phase_count = 1,            /* split-phase 120/240 V               */
        .hybrid      = true,

        .feat_export_to_grid = true,  /* hybrid grid-tie: export/feed-in     */
        .feat_ac_couple      = true,  /* can AC-couple an external GT PV inv  */
        .feat_generator_port = true,

        .layout          = INV_IMAGE_APP_OVER_BL,
        .flash_base      = 0x08000000UL,
        .flash_size      = 256U * 1024U, /* App region tops at 0x08040000    */
        .bootloader_size = 0xC800UL,     /* 0x08000000..0x0800C7FF reserved   */
        .vector_addr     = 0x0800C800UL,
        .sram_size       = 64U * 1024U,
    },
};

const inv_variant_t *inv_variant_by_model(inv_model_id_t id)
{
    if ((unsigned)id >= (unsigned)INV_MODEL__COUNT) id = INV_MODEL_12000XP;
    return &k_variants[id];
}

const inv_variant_t *inv_variant(void)
{
#if defined(INV_VARIANT_18KPV)
    return &k_variants[INV_MODEL_18KPV];
#else
    return &k_variants[INV_MODEL_12000XP];
#endif
}

bool inv_ir_active(uint16_t input_reg)
{
    /* The only register deltas between the two recovered variants are the
     * 3rd-MPPT telemetry slots. On a 2-MPPT build they are inactive. Keep this
     * as an explicit allow/deny so new deltas get added in one place. */
    if (inv_variant()->mppt_count < 3) {
        switch (input_reg) {
            case 3:   /* IR_VPV3      */
            case 9:   /* IR_PPV3      */
            case 30:  /* IR_EPV3_DAY  */
            case 44:  /* IR_EPV3_ALL_L*/
            case 45:  /* IR_EPV3_ALL_H*/
                return false;
            default:
                break;
        }
    }
    return true;
}
