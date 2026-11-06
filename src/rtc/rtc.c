/*
 * ARM wall-clock software calendar (see include/inv/rtc.h).
 *
 * Pure, host-testable: the carry chain, days-in-month and leap handling match
 * the factory calendar advance (docs/36) so the RTC_WALK contract holds for both.
 */
#include "inv/rtc.h"

inv_rtc_t g_rtc;

bool rtc_is_leap(uint8_t year)
{
    /* `year` is an offset from 2000; 2000 is a leap year and the field cannot
     * reach 2100 within a u8 offset, so the simple divisible-by-4 rule holds. */
    return (year % 4u) == 0u;
}

uint8_t rtc_days_in_month(uint8_t month, uint8_t year)
{
    static const uint8_t dim[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
    if (month < 1u || month > 12u) return 31u;              /* defensive */
    if (month == 2u && rtc_is_leap(year)) return 29u;
    return dim[month - 1u];
}

/* Weekday (0=Sun..6=Sat) for the Gregorian date 2000+year / month / day
 * (Zeller's congruence, adjusted so 0=Sunday). */
static uint8_t weekday_of(uint8_t day, uint8_t month, uint8_t year)
{
    int y = 2000 + (int)year, m = (int)month;
    if (m < 3) { m += 12; y -= 1; }
    int k = y % 100, j = y / 100;
    int h = (day + (13 * (m + 1)) / 5 + k + k / 4 + j / 4 + 5 * j) % 7;  /* 0=Sat */
    return (uint8_t)((h + 6) % 7);                                        /* 0=Sun */
}

void rtc_tick(void)
{
    if (++g_rtc.sec < 60u) return;
    g_rtc.sec = 0u;
    if (++g_rtc.minute < 60u) return;
    g_rtc.minute = 0u;
    if (++g_rtc.hour < 24u) return;
    g_rtc.hour = 0u;
    if (++g_rtc.day <= rtc_days_in_month(g_rtc.month, g_rtc.year)) {
        g_rtc.weekday = weekday_of(g_rtc.day, g_rtc.month, g_rtc.year);
        return;
    }
    g_rtc.day = 1u;
    if (++g_rtc.month <= 12u) {
        g_rtc.weekday = weekday_of(g_rtc.day, g_rtc.month, g_rtc.year);
        return;
    }
    g_rtc.month = 1u;
    g_rtc.year++;
    g_rtc.weekday = weekday_of(g_rtc.day, g_rtc.month, g_rtc.year);
}

void rtc_set(uint8_t sec, uint8_t minute, uint8_t hour,
             uint8_t day, uint8_t month, uint8_t year)
{
    g_rtc.sec = sec; g_rtc.minute = minute; g_rtc.hour = hour;
    g_rtc.day = day; g_rtc.month = month; g_rtc.year = year;
    g_rtc.weekday = weekday_of(day, month, year);
}

void rtc_set_from_modbus(uint16_t hr12, uint16_t hr13, uint16_t hr14)
{
    rtc_set((uint8_t)(hr14 >> 8), (uint8_t)(hr14 & 0xFFu),   /* sec, minute */
            (uint8_t)(hr13 >> 8),                            /* hour */
            (uint8_t)(hr13 & 0xFFu),                         /* day */
            (uint8_t)(hr12 >> 8),                            /* month */
            (uint8_t)(hr12 & 0xFFu));                        /* year */
}

uint16_t rtc_now_minutes(void)
{
    return (uint16_t)(60u * g_rtc.hour + g_rtc.minute);
}
