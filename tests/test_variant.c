/* Host tests for the product-variant abstraction (docs/09).  make test
 *
 * Verifies the recovered descriptors for both models and the register-gating
 * helper. The default build targets the 12000XP, so inv_variant() must report
 * that here; both descriptors are always queryable via inv_variant_by_model().
 */
#include "inv/variant.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    const inv_variant_t *x12 = inv_variant_by_model(INV_MODEL_12000XP);
    const inv_variant_t *x18 = inv_variant_by_model(INV_MODEL_18KPV);

    /* --- 12000XP: non-hybrid, 2 MPPT, monolithic image at flash base --- */
    CHECK(x12->id == INV_MODEL_12000XP,        "12k id");
    CHECK(x12->mppt_count == 2,                "12k has 2 MPPT");
    CHECK(x12->hybrid == false,                "12k is non-hybrid");
    CHECK(x12->feat_export_to_grid == false,   "12k cannot export to grid");
    CHECK(x12->layout == INV_IMAGE_MONOLITHIC, "12k monolithic layout");
    CHECK(x12->vector_addr == 0x08000000UL,    "12k vectors at flash base");
    CHECK(x12->bootloader_size == 0,           "12k has no reserved bootloader");
    CHECK(x12->flash_size == 512u*1024u,       "12k is a 512K part");
    CHECK(strcmp(x12->model_code, "ceaa") == 0,"12k model code");
    CHECK(strcmp(x12->image_sig,  "SNEC") == 0,"12k image signature");

    /* --- 18kPV: hybrid, 3 MPPT, App relocated above a bootloader --- */
    CHECK(x18->id == INV_MODEL_18KPV,          "18k id");
    CHECK(x18->mppt_count == 3,                "18k has 3 MPPT");
    CHECK(x18->hybrid == true,                 "18k is hybrid");
    CHECK(x18->feat_export_to_grid == true,    "18k can export to grid");
    CHECK(x18->layout == INV_IMAGE_APP_OVER_BL,"18k App-over-bootloader layout");
    CHECK(x18->vector_addr == 0x0800C800UL,    "18k vectors relocated to 0x0800C800");
    CHECK(x18->bootloader_size == 0xC800UL,    "18k reserves a 0xC800 bootloader");
    CHECK(strcmp(x18->model_code, "FAAB") == 0,"18k model code");
    CHECK(strcmp(x18->image_sig,  "EAA1") == 0,"18k image signature");

    /* App vectors must sit exactly above the reserved bootloader. */
    CHECK(x18->flash_base + x18->bootloader_size == x18->vector_addr,
          "18k App vectors are directly above the bootloader");

    /* --- 6000XP: non-hybrid 2-MPPT, App relocated above a 20 KB bootloader --- */
    const inv_variant_t *x6 = inv_variant_by_model(INV_MODEL_6000XP);
    CHECK(x6->id == INV_MODEL_6000XP,          "6k id");
    CHECK(x6->mppt_count == 2,                 "6k has 2 MPPT");
    CHECK(x6->hybrid == false,                 "6k is non-hybrid");
    CHECK(x6->layout == INV_IMAGE_APP_OVER_BL, "6k App-over-bootloader layout");
    CHECK(x6->vector_addr == 0x08005000UL,     "6k vectors relocated to 0x08005000");
    CHECK(x6->bootloader_size == 0x5000UL,     "6k reserves a 0x5000 bootloader");
    CHECK(x6->flash_size == 256u*1024u,        "6k App region tops at 256K");
    CHECK(strcmp(x6->model_code, "ccaa") == 0, "6k model code");
    CHECK(strcmp(x6->image_sig,  "SNCC") == 0, "6k image signature");
    CHECK(x6->flash_base + x6->bootloader_size == x6->vector_addr,
          "6k App vectors are directly above the bootloader");

    /* --- active (build-time) variant: default is the 12000XP --- */
    CHECK(inv_variant() == x12,                "default build targets 12000XP");
    CHECK(inv_has_mppt3() == false,            "default build: no 3rd MPPT");
    CHECK(inv_is_hybrid() == false,            "default build: non-hybrid");

    /* --- register gating: PV3 slots inactive on a 2-MPPT build --- */
    CHECK(inv_ir_active(1)  == true,           "VPV1 active");
    CHECK(inv_ir_active(2)  == true,           "VPV2 active");
    CHECK(inv_ir_active(3)  == false,          "VPV3 gated off on 12000XP");
    CHECK(inv_ir_active(9)  == false,          "PPV3 gated off on 12000XP");
    CHECK(inv_ir_active(30) == false,          "EPV3_DAY gated off on 12000XP");
    CHECK(inv_ir_active(44) == false,          "EPV3_ALL_L gated off on 12000XP");
    CHECK(inv_ir_active(45) == false,          "EPV3_ALL_H gated off on 12000XP");
    CHECK(inv_ir_active(4)  == true,           "VBAT active (not a PV3 slot)");

    printf("test_variant: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
