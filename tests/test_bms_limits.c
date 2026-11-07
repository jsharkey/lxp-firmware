/*
 * Host unit tests for the BMS working-limit derivation (docs/39 T11a).
 * Build & run:  make test  -- no hardware needed.
 *
 * The factory oracle (black-box on the ceaa-07xx image) is IR 83 =
 * min(0x351 charge-V, HR 99); this sweeps that min() over the boundaries.
 */
#include "inv/bms_limits.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(cond, msg) do { g_run++; if (!(cond)) { \
    printf("  FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    /* BMS below the setting -> the pack's limit wins (the usual case). */
    CHECK(inv_bms_charge_volt_ref(560, 574) == 560, "bms<setting: bms wins (560)");
    CHECK(inv_bms_charge_volt_ref(570, 574) == 570, "bms<setting: bms wins (570)");

    /* BMS above the setting -> the setting clamps it down. */
    CHECK(inv_bms_charge_volt_ref(600, 574) == 574, "bms>setting: setting clamps (574)");
    CHECK(inv_bms_charge_volt_ref(600, 520) == 520, "bms>setting: setting clamps (520)");
    CHECK(inv_bms_charge_volt_ref(1000, 590) == 590, "bms>>setting: setting clamps (590)");

    /* Exact-equality boundary: either branch yields the same value. */
    CHECK(inv_bms_charge_volt_ref(574, 574) == 574, "bms==setting (574)");

    /* t-1 / t / t+1 around a crossover at setting=574. */
    CHECK(inv_bms_charge_volt_ref(573, 574) == 573, "crossover t-1 -> bms");
    CHECK(inv_bms_charge_volt_ref(574, 574) == 574, "crossover t   -> equal");
    CHECK(inv_bms_charge_volt_ref(575, 574) == 574, "crossover t+1 -> setting");

    /* Degenerate ends: a 0 input (no/zero limit) wins the min; matches the
     * factory (chgV=0 -> IR 83 = 0). */
    CHECK(inv_bms_charge_volt_ref(0, 574) == 0,     "bms=0 -> 0 (factory-matched)");
    CHECK(inv_bms_charge_volt_ref(560, 0) == 0,     "setting=0 -> 0");
    CHECK(inv_bms_charge_volt_ref(100, 574) == 100, "bms=100 -> 100 (factory-matched)");
    CHECK(inv_bms_charge_volt_ref(0xFFFF, 574) == 574, "bms=max -> setting");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAIL" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
