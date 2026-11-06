/* Host tests for the ARM-computed telemetry serve layer (docs/39 T07). make test */
#include "inv/telemetry.h"
#include "inv/modbus_map.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    /* serve scaling: IR = (u16)(internal_0.1W / 10) */
    CHECK(inv_power_to_ir(0)      == 0,     "0 -> 0");
    CHECK(inv_power_to_ir(1234)   == 123,   "1234 (123.4 W) -> 123 (truncates)");
    CHECK(inv_power_to_ir(1239)   == 123,   "1239 -> 123 (truncates, no round)");
    CHECK(inv_power_to_ir(65535)  == 6553,  "65535 -> 6553");
    CHECK(inv_power_to_ir(100000) == 10000, "100000 (10 kW) -> 10000");
    CHECK(inv_power_to_ir(655350) == 65535, "655350 -> 65535 (u16 max)");
    CHECK(inv_power_to_ir(655360) == 0,     "655360 -> 65536 truncated to u16 = 0");

    /* publish maps each field to its register with the right transform */
    uint16_t ir[160];
    memset(ir, 0xEE, sizeof ir);
    inv_telemetry_t t = {0};
    t.p_pv1 = 32000; t.p_pv2 = 31800; t.p_pv3 = 0;
    t.p_charge = 15000; t.p_discharge = 0;
    t.p_inv = 48000; t.p_rec = 0; t.p_eps = 12000;
    t.s_eps = 1300; t.p_togrid = 20000; t.p_touser = 0;
    t.runtime_s = 90061;                 /* 0x0001_5FCD */
    inv_telemetry_publish(ir, &t);
    CHECK(ir[IR_PPV1] == 3200, "IR7 Ppv1 = 3200 W");
    CHECK(ir[IR_PPV2] == 3180, "IR8 Ppv2 = 3180 W");
    CHECK(ir[IR_PCHARGE] == 1500 && ir[IR_PDISCHARGE] == 0, "IR10/11 charge split");
    CHECK(ir[IR_PINV] == 4800 && ir[IR_PREC] == 0, "IR16/17 Pinv/Prec");
    CHECK(ir[IR_PEPS] == 1200, "IR24 Peps = 1200 W");
    CHECK(ir[IR_SEPS] == 1300, "IR25 Seps served 1:1 (VA)");
    CHECK(ir[IR_PTOGRID] == 2000 && ir[IR_PTOUSER] == 0, "IR26/27 to-grid/to-user");
    CHECK(ir[IR_RUNTIME_L] == 0x5FCD && ir[IR_RUNTIME_H] == 0x0001, "IR69/70 RunningTime u32 split");

    /* runtime ticks only in a running state (>= 3) */
    t.runtime_s = 0;
    inv_telemetry_runtime_tick(&t, 0x00);  /* standby */
    CHECK(t.runtime_s == 0, "runtime does not advance in standby");
    inv_telemetry_runtime_tick(&t, 0x10);  /* running */
    inv_telemetry_runtime_tick(&t, 0x10);
    CHECK(t.runtime_s == 2, "runtime advances 1/s while running");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
