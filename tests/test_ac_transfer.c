/* Host tests for the normal-mode AC-transfer decision (docs/18, T14). make test
 * Mirrors the factory-verified vectors in tests/ac_transfer_contract.py. */
#include "inv/relay.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

#define B20  (1u << 20)
#define MODE(n) ((unsigned)(n) << 29)

static void expect(bool en, uint32_t grid, int epa12, int epb3, const char *m)
{
    bool pa12 = false, pb3 = false;
    inv_ac_transfer_decide(en, grid, &pa12, &pb3);
    CHECK(pa12 == (bool)epa12 && pb3 == (bool)epb3, m);
}

int main(void)
{
    /* disabled -> both open, regardless of grid */
    expect(false, 0,            0, 0, "disabled -> both open");
    expect(false, B20,          0, 0, "disabled + grid ok -> both open");

    /* enabled + grid qualified (bit20 set, bits29-30 != 2) -> PA12 open, PB3 closed */
    expect(true,  B20,          0, 1, "enabled grid-ok (bit20) -> PA12=0 PB3=1");
    expect(true,  B20 | MODE(1),0, 1, "enabled grid-ok (mode 1) -> PA12=0 PB3=1");
    expect(true,  B20 | MODE(3),0, 1, "enabled grid-ok (mode 3) -> PA12=0 PB3=1");

    /* enabled + grid NOT qualified -> PA12 closed, PB3 closed */
    expect(true,  0,            1, 1, "enabled no grid (bit20 clear) -> PA12=1 PB3=1");
    expect(true,  B20 | MODE(2),1, 1, "enabled grid mode 2 (bad) -> PA12=1 PB3=1");
    expect(true,  MODE(1),      1, 1, "enabled bit20 clear + mode1 -> PA12=1 PB3=1");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
