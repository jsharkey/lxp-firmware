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
    CHECK(accepts(HR_PV_INPUT_MODEL, 7),  "HR20=7 (max) accepted");
    CHECK(accepts(HR_ACCHG_POWER_PCT, 50), "HR66=50 accepted");
    CHECK(accepts(HR_ACCHG_POWER_PCT, 100), "HR66=100 (max) accepted");
    CHECK(accepts(HR_COM_ADDR, 10),       "HR15=10 accepted");
    CHECK(accepts(HR_EOD, 50),            "HR105=50 accepted");

    /* out-of-range rejected with ILLEGAL_VALUE (3) -- not clamped, not stored */
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

    /* a register with no recovered range is accepted verbatim */
    CHECK(accepts(HR_DISCHG_CURR, 12345), "HR102 (no range) accepted verbatim");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
