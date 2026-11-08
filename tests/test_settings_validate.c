/* Host tests for settings_validate() (docs/39 T04). make test */
#include "inv/settings_validate.h"
#include "inv/modbus_map.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

static int accepts(uint16_t reg, uint16_t val) {
    sv_result_t r = settings_validate(reg, val);
    return r.exc == MB_OK && r.value == val;
}
static int rejects(uint16_t reg, uint16_t val, mb_exception_t exc) {
    return settings_validate(reg, val).exc == exc;
}

int main(void)
{
    /* in-range accepted (echo) */
    CHECK(accepts(HR_PV_INPUT_MODEL, 3),  "HR20=3 accepted");
    CHECK(accepts(HR_PV_INPUT_MODEL, 6),  "HR20=6 (factory max) accepted");
    CHECK(accepts(HR_ACCHG_POWER_PCT, 50), "HR66=50 accepted");
    CHECK(accepts(HR_ACCHG_POWER_PCT, 100), "HR66=100 (max) accepted");
    CHECK(accepts(HR_COM_ADDR, 10),       "HR15=10 accepted");
    CHECK(accepts(HR_EOD, 50),            "HR105=50 accepted");

    /* out-of-range rejected with ILLEGAL_VALUE (3) -- not clamped, not stored */
    CHECK(rejects(HR_PV_INPUT_MODEL, 7,  MB_EXC_ILLEGAL_VALUE), "HR20=7 rejected (factory max 6, not spec 7)");
    CHECK(rejects(HR_PV_INPUT_MODEL, 8,  MB_EXC_ILLEGAL_VALUE), "HR20=8 rejected exc3");
    CHECK(rejects(HR_ACCHG_POWER_PCT, 101, MB_EXC_ILLEGAL_VALUE), "HR66=101 rejected exc3");
    CHECK(rejects(HR_COM_ADDR, 151,  MB_EXC_ILLEGAL_VALUE), "HR15=151 rejected exc3");
    CHECK(rejects(HR_EOD, 9,         MB_EXC_ILLEGAL_VALUE), "HR105=9 (below min) rejected exc3");

    /* factory one-sided enforcement, replicated for parity (docs/31) */
    CHECK(accepts(HR_EOD, 91),            "HR105=91 accepted (no upper bound, docs/31)");
    CHECK(accepts(HR_CHARGE_CURR, 141),   "HR101=141 accepted (no upper bound, docs/31)");

    /* read-only registers rejected with SLAVE_FAILURE (4) */
    CHECK(rejects(HR_SLAVE_COM_VER, 0x1234, MB_EXC_SLAVE_FAILURE), "HR9 read-only exc4");
    CHECK(rejects(HR_CNTL_FW_VER,  0x1234, MB_EXC_SLAVE_FAILURE), "HR10 read-only exc4");

    /* --- T24b: factory bounds recovered by the whole-HR sweep (docs/31 Q11) --- */
    /* tighter-than-spec maxes */
    CHECK(rejects(HR_REACTIVE_CMD_TYPE, 7, MB_EXC_ILLEGAL_VALUE), "HR59=7 rejected (factory max 6)");
    CHECK(rejects(HR_LINE_MODE, 2, MB_EXC_ILLEGAL_VALUE), "HR146=2 rejected (GEN, cold state)");
    CHECK(accepts(HR_LINE_MODE, 1),       "HR146=1 accepted");
    CHECK(rejects(HR_CUT_VOLT_DISCHG, 500, MB_EXC_ILLEGAL_VALUE), "HR100=500 rejected (factory max 499)");
    CHECK(accepts(HR_CUT_VOLT_DISCHG, 400), "HR100=400 accepted");
    CHECK(rejects(HR_GEN_CHG_START_V, 520, MB_EXC_ILLEGAL_VALUE), "HR194=520 rejected (factory max 519)");
    /* HR 162/164 discharge cut-off thresholds: dongle-writable, factory bounds (T17) */
    CHECK(accepts(HR_BAT_LOW_VOLT, 420),  "HR162=420 accepted (cut-off V min)");
    CHECK(accepts(HR_BAT_LOW_VOLT, 560),  "HR162=560 accepted (cut-off V max)");
    CHECK(rejects(HR_BAT_LOW_VOLT, 419, MB_EXC_ILLEGAL_VALUE), "HR162=419 rejected (below min)");
    CHECK(rejects(HR_BAT_LOW_VOLT, 561, MB_EXC_ILLEGAL_VALUE), "HR162=561 rejected (above max)");
    CHECK(accepts(HR_BAT_LOW_SOC, 15),    "HR164=15 accepted (cut-off SOC min)");
    CHECK(accepts(HR_BAT_LOW_SOC, 100),   "HR164=100 accepted (cut-off SOC max)");
    CHECK(rejects(HR_BAT_LOW_SOC, 14, MB_EXC_ILLEGAL_VALUE), "HR164=14 rejected (below min)");
    CHECK(rejects(HR_BAT_LOW_SOC, 101, MB_EXC_ILLEGAL_VALUE), "HR164=101 rejected (above max)");
    /* one-sided / shifted lower bounds */
    CHECK(rejects(HR_EOD, 10, MB_EXC_ILLEGAL_VALUE), "HR105=10 rejected (factory min 11, not spec 10)");
    CHECK(rejects(HR_CHGFIRST_SOC, 0, MB_EXC_ILLEGAL_VALUE), "HR75=0 rejected (min>0)");
    CHECK(accepts(HR_CHGFIRST_SOC, 200),  "HR75=200 accepted (no upper bound)");
    CHECK(rejects(HR_GEN_CHG_START_SOC, 0, MB_EXC_ILLEGAL_VALUE), "HR196=0 rejected (min 1)");
    CHECK(rejects(HR_MAX_GEN_CHG_CURR, 0, MB_EXC_ILLEGAL_VALUE), "HR198=0 rejected (min 1)");
    CHECK(accepts(HR_MAX_GEN_CHG_CURR, 61), "HR198=61 accepted (no upper bound, above spec 60)");
    CHECK(accepts(HR_CHARGE_VOLT_REF, 499), "HR99=499 accepted (below spec min 500)");
    CHECK(rejects(HR_CHARGE_VOLT_REF, 591, MB_EXC_ILLEGAL_VALUE), "HR99=591 rejected (max 590)");
    /* not writable at all -> ILLEGAL_ADDRESS (2) */
    CHECK(rejects(HR_START_PV_VOLT, 1000, MB_EXC_ILLEGAL_ADDRESS), "HR22 not writable exc2");
    CHECK(rejects(HR_ACCHG_SOC_LIMIT, 50, MB_EXC_ILLEGAL_ADDRESS), "HR67 not writable exc2");
    CHECK(rejects(HR_CHGFIRST_POWER, 50, MB_EXC_ILLEGAL_ADDRESS), "HR74 not writable exc2");
    CHECK(rejects(HR_FDISCHG_POWER, 50, MB_EXC_ILLEGAL_ADDRESS), "HR82 not writable exc2");
    CHECK(rejects(HR_OUTPUT_PRIO_CFG, 1, MB_EXC_ILLEGAL_ADDRESS), "HR145 not writable exc2");
    CHECK(rejects(HR_BAT_LOW_BACK_VOLT, 460, MB_EXC_ILLEGAL_ADDRESS), "HR163 recovery-V not dongle-writable exc2 (T17)");
    CHECK(rejects(HR_BAT_LOW_BACK_SOC, 60, MB_EXC_ILLEGAL_ADDRESS), "HR165 recovery-SOC not dongle-writable exc2 (T17)");
    /* HR112 SetSystemType: value 2 (slave) rejected, 0/1/3 accepted (Q9) */
    CHECK(accepts(HR_SET_SYSTEM_TYPE, 0),  "HR112=0 accepted");
    CHECK(rejects(HR_SET_SYSTEM_TYPE, 2, MB_EXC_ILLEGAL_VALUE), "HR112=2 (slave) rejected");
    CHECK(accepts(HR_SET_SYSTEM_TYPE, 3),  "HR112=3 accepted");

    /* a register with no recovered range is accepted verbatim */
    CHECK(accepts(HR_DISCHG_CURR, 12345), "HR102 (no range) accepted verbatim");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
