/* Host tests for the energy accumulator (docs/37).  make test */
#include "inv/energy.h"
#include "inv/modbus_map.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

static void reset(void) { memset(&g_energy, 0, sizeof g_energy); }

int main(void)
{
    uint16_t ir[160];

    /* 1 count per tick (power/2 == threshold) */
    reset();
    energy_set_power(0, 7200002u);
    for (int i = 0; i < 5; i++) energy_tick(0x40);
    CHECK(g_energy.all[0] == 5 && g_energy.day[0] == 5, "5 ticks -> 5 counts (day+all)");

    /* gated off when not running */
    reset();
    energy_set_power(0, 7200002u);
    for (int i = 0; i < 5; i++) energy_tick(0x02);     /* state < ENERGY_RUN_STATE */
    CHECK(g_energy.all[0] == 0 && g_energy.day[0] == 0, "state<3 gates accumulation off");

    /* one count per two ticks (power/2 == threshold/2) */
    reset();
    energy_set_power(0, 3600002u);
    for (int i = 0; i < 4; i++) energy_tick(0x40);
    CHECK(g_energy.all[0] == 2 && g_energy.day[0] == 2, "sub-threshold: 1 count / 2 ticks");

    /* publish to the input-register image: IR 28 (daily), IR 40/41 (cumulative) */
    reset();
    energy_set_power(0, 7200002u);
    for (int i = 0; i < 70000; i++) energy_tick(0x40);  /* enough to exceed 16 bits */
    memset(ir, 0, sizeof ir);
    energy_publish(ir);
    CHECK(ir[IR_EPV1_DAY] == (uint16_t)g_energy.day[0], "IR 28 = Epv1_day");
    CHECK(((uint32_t)ir[IR_EPV1_ALL_L] | ((uint32_t)ir[IR_EPV1_ALL_H] << 16)) == g_energy.all[0],
          "IR 40/41 = Epv1_all 32-bit L/H");
    CHECK(g_energy.all[0] == 70000, "70000 ticks -> 70000 counts (crosses 16 bits)");

    /* daily rollover: cross a day boundary -> daily resets, cumulative persists */
    reset();
    energy_set_power(0, 7200002u);
    for (int i = 0; i < 5; i++) energy_tick(0x40);
    energy_rollover(15);               /* first observation: latch, no reset */
    CHECK(g_energy.day[0] == 5, "rollover latch does not reset on first observation");
    energy_rollover(15);               /* same day: no reset */
    CHECK(g_energy.day[0] == 5, "same day: daily persists");
    energy_rollover(16);               /* day change: daily resets */
    CHECK(g_energy.day[0] == 0, "day change: Epv1_day resets to 0");
    CHECK(g_energy.all[0] == 5, "day change: Epv1_all cumulative persists");

    /* all ten channels (IR 28-37 daily, IR 40-59 cumulative): each channel maps to
     * its own day register (28+ch) and its own 32-bit L/H cumulative pair
     * (40+2*ch / 41+2*ch), with no cross-wiring, and the cumulative high word
     * carries past 0xFFFF. Distinct value per channel so a swapped index is caught. */
    reset();
    for (int ch = 0; ch < ENERGY_NCH; ch++) {
        g_energy.day[ch] = (uint16_t)(100 + ch);               /* distinct daily */
        g_energy.all[ch] = 0x10000u * (uint32_t)(ch + 1) + (uint32_t)ch;  /* >0xFFFF: carry */
    }
    memset(ir, 0, sizeof ir);
    energy_publish(ir);
    for (int ch = 0; ch < ENERGY_NCH; ch++) {
        uint32_t all = (uint32_t)ir[IR_EPV1_ALL_L + 2 * ch]
                     | ((uint32_t)ir[IR_EPV1_ALL_L + 2 * ch + 1] << 16);
        CHECK(ir[IR_EPV1_DAY + ch] == (uint16_t)(100 + ch),
              "IR 28+ch = day[ch] for every channel");
        CHECK(all == 0x10000u * (uint32_t)(ch + 1) + (uint32_t)ch,
              "IR 40+2ch L/H = all[ch] (32-bit, high word carried) for every channel");
    }

    /* channel independence: drive only two channels through real accumulation and
     * confirm the rest stay 0 (the per-tick loop does not leak between channels). */
    reset();
    energy_set_power(3, 7200002u);        /* 1 count/tick on channel 3 */
    energy_set_power(7, 3600002u);        /* 1 count / 2 ticks on channel 7 */
    for (int i = 0; i < 6; i++) energy_tick(0x40);
    CHECK(g_energy.day[3] == 6 && g_energy.all[3] == 6, "channel 3 accumulates independently");
    CHECK(g_energy.day[7] == 3 && g_energy.all[7] == 3, "channel 7 accumulates at its own rate");
    {
        int others_zero = 1;
        for (int ch = 0; ch < ENERGY_NCH; ch++)
            if (ch != 3 && ch != 7 && (g_energy.day[ch] || g_energy.all[ch])) others_zero = 0;
        CHECK(others_zero, "undriven channels stay 0 (no cross-channel leakage)");
    }

    /* energy_reset_all (HR 11 EnergyRecordClr) clears everything */
    energy_set_power(0, 7200002u);
    for (int i = 0; i < 3; i++) energy_tick(0x40);
    energy_reset_all();
    CHECK(g_energy.all[0] == 0 && g_energy.day[0] == 0 && g_energy.sub[0] == 0,
          "energy_reset_all clears cumulative/daily/sub");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
