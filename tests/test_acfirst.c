/* Host tests for the AC-First window evaluator (docs/25).  make test
 *
 * Verifies the pure window-vs-clock logic that main.c surfaces as IR 126 bit 8:
 * the packed (minute<<8)|hour encoding, start-inclusive / end-exclusive edges,
 * midnight wrap, empty windows, and the multi-window OR.
 */
#include "inv/acfirst.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* pack a window register the way Modbus carries it: (minute<<8)|hour */
static uint16_t w(int hour, int minute) { return (uint16_t)((minute << 8) | hour); }

int main(void)
{
    /* encoding helpers */
    CHECK(acfirst_reg_minutes(w(6, 0))  == 360,  "06:00 -> 360 min");
    CHECK(acfirst_reg_minutes(w(8, 30)) == 510,  "08:30 -> 510 min");
    CHECK(acfirst_clock_minutes(1 | (6 << 8), 0)        == 360, "clock 06:00 (date=1)");
    CHECK(acfirst_clock_minutes(1 | (7 << 8), 30 | (5<<8)) == 450, "clock 07:30 (sec ignored)");

    /* single window 06:00-08:00: start-inclusive, end-exclusive */
    uint16_t win[6] = { w(6,0), w(8,0), 0,0, 0,0 };
    CHECK(!acfirst_window_active(win, 3, acfirst_reg_minutes(w(5,59))), "05:59 off");
    CHECK( acfirst_window_active(win, 3, acfirst_reg_minutes(w(6,0))),  "06:00 active (start incl)");
    CHECK( acfirst_window_active(win, 3, acfirst_reg_minutes(w(7,30))), "07:30 active");
    CHECK( acfirst_window_active(win, 3, acfirst_reg_minutes(w(7,59))), "07:59 active");
    CHECK(!acfirst_window_active(win, 3, acfirst_reg_minutes(w(8,0))),  "08:00 off (end excl)");
    CHECK(!acfirst_window_active(win, 3, acfirst_reg_minutes(w(9,0))),  "09:00 off");

    /* empty window (start == end) is never active */
    uint16_t empty[6] = { w(3,0), w(3,0), 0,0, 0,0 };
    CHECK(!acfirst_window_active(empty, 3, acfirst_reg_minutes(w(3,0))), "empty window never active");

    /* midnight wrap 22:00-02:00 */
    uint16_t wrap[6] = { w(22,0), w(2,0), 0,0, 0,0 };
    CHECK( acfirst_window_active(wrap, 3, acfirst_reg_minutes(w(23,0))), "23:00 in wrap window");
    CHECK( acfirst_window_active(wrap, 3, acfirst_reg_minutes(w(1,0))),  "01:00 in wrap window");
    CHECK(!acfirst_window_active(wrap, 3, acfirst_reg_minutes(w(2,0))),  "02:00 off (wrap end excl)");
    CHECK(!acfirst_window_active(wrap, 3, acfirst_reg_minutes(w(12,0))), "12:00 off (outside wrap)");

    /* multi-window OR: second window matches while the first is empty */
    uint16_t multi[6] = { 0,0, w(6,0), w(8,0), 0,0 };
    CHECK( acfirst_window_active(multi, 3, acfirst_reg_minutes(w(7,0))), "07:00 active via window 1");

    printf(g_fail ? "test_acfirst: %d/%d FAILED\n" : "test_acfirst: %d/%d passed\n",
           g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
