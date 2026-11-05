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

    /* 0x356 measurements: [0:1] V 0.01V, [2:3] I 0.01A s16, [4:5] T 0.1C s16 */
    {
        uint8_t d[6] = { 0xCD, 0x14,            /* 5325 = 0x14CD */
                         0x9C, 0xFF,            /* -100  = 0xFF9C (discharge) */
                         0xE7, 0x00 };          /* 231 */
        CHECK(bms_can_on_frame(&p, BMS_CAN_ID_VIT, d, sizeof d), "0x356 consumed");
        CHECK(p.measured_valid, "0x356 marks measurements valid");
        CHECK(p.voltage_cv == 5325, "0x356 decodes voltage");
        CHECK(p.current_ca == -100, "0x356 decodes signed current");
        CHECK(p.temp_dc == 231, "0x356 decodes temperature");
    }

    /* 0x351 limits: [0:1] charge voltage limit 0.1V */
    {
        uint8_t d[8] = { 0x30, 0x02, 0,0, 0,0, 0,0 };  /* 560 = 0x0230 */
        CHECK(bms_can_on_frame(&p, BMS_CAN_ID_LIMITS, d, sizeof d), "0x351 consumed");
        CHECK(p.limits_valid, "0x351 marks limits valid");
        CHECK(p.charge_volt_dv == 560, "0x351 decodes charge voltage limit");
    }

    /* short 0x356 is rejected */
    {
        uint8_t d[4] = {1,2,3,4};
        CHECK(!bms_can_on_frame(&p, BMS_CAN_ID_VIT, d, sizeof d), "0x356 too short -> ignored");
    }

    /* 0x359 protection/alarm: [0:1] fault bits, [2:3] warn bits */
    {
        uint8_t d[8] = { 0x02, 0x01, 0x08, 0x04, 1, 'P', 'N', 0 };  /* 0x0102, 0x0408 */
        CHECK(bms_can_on_frame(&p, BMS_CAN_ID_ALARM_A, d, sizeof d), "0x359 consumed");
        CHECK(p.alarms_valid, "0x359 marks alarms valid");
        CHECK(p.fault_bits == 0x0102, "0x359 decodes fault bits");
        CHECK(p.warn_bits  == 0x0408, "0x359 decodes warn bits");
        CHECK(p.module_count == 1, "0x359 decodes module count");
    }

    /* 0x35A is NOT consumed (received but not exposed on Modbus; see docs/31) */
    {
        uint8_t d[8] = {0xFF,0xFF,0xFF,0xFF,0,0,0,0};
        CHECK(!bms_can_on_frame(&p, BMS_CAN_ID_ALARM_B, d, sizeof d), "0x35A not consumed");
    }

    printf("test_bms_can: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
