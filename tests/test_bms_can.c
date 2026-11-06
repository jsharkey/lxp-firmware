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

    /* ===================================================================== *
     * Field sweep: every decoded field, its edges, and the DLC guards and    *
     * frame independence that feed the IR 81-106 BMS block (docs/20,         *
     * docs/modbus-dongle/IR081_106-BMS.md).                                  *
     * ===================================================================== */

    /* 0x355 SOC/SOH endpoints, on a fresh pack (minimum DLC 4, no hi-res). */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t lo[4] = { 0, 0, 0, 0 };
        CHECK(bms_can_on_frame(&q, BMS_CAN_ID_SOC_SOH, lo, sizeof lo), "0x355 DLC4 accepted");
        CHECK(q.soc == 0 && q.soh == 0, "0x355 SOC/SOH = 0 decodes");
        uint8_t hi[4] = { 100, 0, 100, 0 };
        bms_can_on_frame(&q, BMS_CAN_ID_SOC_SOH, hi, sizeof hi);
        CHECK(q.soc == 100 && q.soh == 100, "0x355 SOC/SOH = 100 decodes");
        uint8_t d3[3] = { 50, 0, 50 };
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_SOC_SOH, d3, sizeof d3), "0x355 DLC3 -> ignored");
    }

    /* 0x356 signedness across all three fields: + current = charge, - current
     * = discharge; temperature below zero; a large positive voltage. (The raw
     * s16 is what reaches IR 98/103; the physical current unit is noted as a
     * doc discrepancy in docs/31 -- the register passes the value 1:1.) */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t chg[6] = { 0x10, 0x27,          /* 10000 = 0x2710  (100.00 V) */
                           0xFA, 0x00,          /* +250  (charge)             */
                           0xCE, 0xFF };        /* -50   (sub-zero temp)      */
        CHECK(bms_can_on_frame(&q, BMS_CAN_ID_VIT, chg, sizeof chg), "0x356 DLC6 accepted");
        CHECK(q.voltage_cv == 10000, "0x356 large positive voltage");
        CHECK(q.current_ca == 250,   "0x356 positive current (charge)");
        CHECK(q.temp_dc   == -50,    "0x356 sub-zero temperature");
        uint8_t d5[5] = { 1, 0, 2, 0, 3 };
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_VIT, d5, sizeof d5), "0x356 DLC5 -> ignored");
    }

    /* 0x351: charge voltage limit endpoints, and the DLC-<2 guard. (The map's
     * current/discharge-limit fields are not consumed yet -- see the map.) */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t z[8] = { 0 };
        bms_can_on_frame(&q, BMS_CAN_ID_LIMITS, z, sizeof z);
        CHECK(q.charge_volt_dv == 0, "0x351 charge Vlim = 0 decodes");
        uint8_t big[8] = { 0xFF, 0xFF, 0,0, 0,0, 0,0 };
        bms_can_on_frame(&q, BMS_CAN_ID_LIMITS, big, sizeof big);
        CHECK(q.charge_volt_dv == 0xFFFF, "0x351 charge Vlim = 0xFFFF decodes");
        uint8_t d1[1] = { 7 };
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_LIMITS, d1, sizeof d1), "0x351 DLC1 -> ignored");
    }

    /* 0x359: DLC4 sets fault/warn but NOT module_count; DLC5+ sets it too;
     * DLC3 is rejected. */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t d4[4] = { 0x34, 0x12, 0x78, 0x56 };   /* 0x1234, 0x5678 */
        CHECK(bms_can_on_frame(&q, BMS_CAN_ID_ALARM_A, d4, sizeof d4), "0x359 DLC4 accepted");
        CHECK(q.fault_bits == 0x1234 && q.warn_bits == 0x5678, "0x359 DLC4 fault/warn");
        CHECK(q.module_count == 0, "0x359 DLC4 leaves module_count unset");
        uint8_t d5[5] = { 0,0, 0,0, 7 };
        bms_can_on_frame(&q, BMS_CAN_ID_ALARM_A, d5, sizeof d5);
        CHECK(q.module_count == 7, "0x359 DLC5 sets module_count");
        uint8_t d3[3] = { 1, 2, 3 };
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_ALARM_A, d3, sizeof d3), "0x359 DLC3 -> ignored");
    }

    /* Frame independence: one frame sets only its own *_valid flag. */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t d[8] = { 0x30, 0x02, 0,0, 0,0, 0,0 };
        bms_can_on_frame(&q, BMS_CAN_ID_LIMITS, d, sizeof d);
        CHECK(q.limits_valid, "0x351 sets limits_valid");
        CHECK(!q.soc_soh_valid && !q.measured_valid && !q.alarms_valid,
              "0x351 does not set unrelated valid flags");
    }

    /* Unknown / control IDs are never consumed and set no state. */
    {
        bms_pack_t q; bms_can_init(&q);
        uint8_t d[8] = { 1,2,3,4,5,6,7,8 };
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_EXT_STATUS, d, sizeof d), "0x35B not consumed");
        CHECK(!bms_can_on_frame(&q, BMS_CAN_ID_INV_300,    d, sizeof d), "0x300 not consumed");
        CHECK(!bms_can_on_frame(&q, 0x123,                 d, sizeof d), "arbitrary ID not consumed");
        CHECK(!q.soc_soh_valid && !q.measured_valid && !q.limits_valid && !q.alarms_valid,
              "unknown frames leave the pack untouched");
    }

    printf("test_bms_can: %d checks, %d failed\n", g_run, g_fail);
    return g_fail ? 1 : 0;
}
