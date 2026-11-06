/* Host tests for the ARM wall-clock calendar (docs/36).  make test
 *
 * The carry chain, days-in-month and leap handling must match the factory
 * calendar advance so the shared RTC_WALK contract (tests/arm_sim_contract.py,
 * run against both firmwares under Unicorn) holds. These host tests pin the pure
 * logic directly; they use the same boundary vectors as that contract.
 */
#include "inv/rtc.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* walk from a start time by `secs` seconds, return the 6-field calendar */
static void walk(int sec,int mn,int hr,int day,int mon,int yr, int secs,
                 uint8_t out[6])
{
    rtc_set((uint8_t)sec,(uint8_t)mn,(uint8_t)hr,(uint8_t)day,(uint8_t)mon,(uint8_t)yr);
    for (int i = 0; i < secs; i++) rtc_tick();
    out[0]=g_rtc.sec; out[1]=g_rtc.minute; out[2]=g_rtc.hour;
    out[3]=g_rtc.day; out[4]=g_rtc.month; out[5]=g_rtc.year;
}
static int eq(const uint8_t a[6], int s,int m,int h,int d,int mo,int y)
{ return a[0]==s&&a[1]==m&&a[2]==h&&a[3]==d&&a[4]==mo&&a[5]==y; }

int main(void)
{
    /* leap + days-in-month */
    CHECK(rtc_is_leap(24) && !rtc_is_leap(23), "2024 leap, 2023 not");
    CHECK(rtc_is_leap(0), "2000 is leap");
    CHECK(rtc_days_in_month(2, 24) == 29, "Feb 2024 = 29");
    CHECK(rtc_days_in_month(2, 23) == 28, "Feb 2023 = 28");
    CHECK(rtc_days_in_month(4, 24) == 30 && rtc_days_in_month(1, 24) == 31, "Apr 30, Jan 31");

    uint8_t o[6];
    walk(0,0,0,1,1,24, 1, o);             CHECK(eq(o,1,0,0,1,1,24), "tick +1s");
    walk(58,0,0,1,1,24, 4, o);            CHECK(eq(o,2,1,0,1,1,24), "minute carry");
    walk(58,59,0,1,1,24, 4, o);           CHECK(eq(o,2,0,1,1,1,24), "hour carry");
    walk(58,59,23,1,1,24, 4, o);          CHECK(eq(o,2,0,0,2,1,24), "day carry");
    walk(58,59,23,30,4,24, 4, o);         CHECK(eq(o,2,0,0,1,5,24), "30-day month -> next");
    walk(58,59,23,28,2,23, 4, o);         CHECK(eq(o,2,0,0,1,3,23), "non-leap Feb 28 -> Mar 1");
    walk(58,59,23,28,2,24, 4, o);         CHECK(eq(o,2,0,0,29,2,24), "leap Feb 28 -> Feb 29");
    walk(58,59,23,29,2,24, 4, o);         CHECK(eq(o,2,0,0,1,3,24), "leap Feb 29 -> Mar 1");
    walk(58,59,23,31,12,24, 4, o);        CHECK(eq(o,2,0,0,1,1,25), "year roll");

    /* set-from-Modbus decode: hr12=year|month<<8, hr13=day|hour<<8, hr14=min|sec<<8 */
    rtc_set_from_modbus(24 | (12 << 8), 31 | (23 << 8), 59 | (58 << 8));
    CHECK(g_rtc.year==24 && g_rtc.month==12 && g_rtc.day==31 &&
          g_rtc.hour==23 && g_rtc.minute==59 && g_rtc.sec==58, "set_from_modbus decode");
    CHECK(rtc_now_minutes() == 23*60+59, "now_minutes");

    printf(g_fail ? "test_rtc: %d/%d FAILED\n" : "test_rtc: %d/%d passed\n",
           g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
