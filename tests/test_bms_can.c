/*
 * Host unit tests for the battery BMS CAN decoder (transport-agnostic core).
 * Build & run:  make test   — no hardware needed. See docs/20.
 */
#include "inv/bms_can.h"
#include "inv/bms_can_map.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(cond, msg) do { g_run++; if (!(cond)) { \
    printf("  FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    bms_pack_t p;
    bms_can_init(&p);

    /* fresh state: nothing decoded yet */
    CHECK(!p.soc_soh_valid, "init: SOC/SOH not yet valid");

    /* 0x355 SOC/SOH: little-endian [0:1] SOC, [2:3] SOH, [4:5] SOC hi-res */
    {
        uint8_t d[6] = { 77, 0, 96, 0, (uint8_t)(7700 & 0xFF), (uint8_t)(7700 >> 8) };
        bool known = bms_can_on_frame(&p, BMS_CAN_ID_SOC_SOH, d, sizeof d);
        CHECK(known, "0x355 is a known telemetry frame");
        CHECK(p.soc_soh_valid, "0x355 marks SOC/SOH valid");
        CHECK(p.soc == 77, "0x355 decodes SOC");
        CHECK(p.soh == 96, "0x355 decodes SOH");
    }

    /* a later frame updates the cached values */
    {
        uint8_t d[6] = { 42, 0, 88, 0, 0, 0 };
        bms_can_on_frame(&p, BMS_CAN_ID_SOC_SOH, d, sizeof d);
        CHECK(p.soc == 42 && p.soh == 88, "0x355 re-decode updates SOC/SOH");
    }

    /* short frame is rejected, leaves state unchanged */
    {
        uint8_t prev_soc = p.soc;
        uint8_t d[2] = { 1, 0 };
        CHECK(!bms_can_on_frame(&p, BMS_CAN_ID_SOC_SOH, d, sizeof d), "0x355 too short -> ignored");
        CHECK(p.soc == prev_soc, "short frame does not corrupt SOC");
    }

    /* an unconsumed telemetry ID is reported as not-known (no update) */
    {
        uint8_t d[8] = {0};
        CHECK(!bms_can_on_frame(&p, BMS_CAN_ID_VIT, d, sizeof d), "0x356 not consumed yet");
    }

    printf("test_bms_can: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
