#ifndef INV_RTC_H
#define INV_RTC_H
/*
 * ARM wall-clock software calendar.
 *
 * The ARM is the system timekeeper (the DSP has no clock -- docs/09/36). This is
 * a 7-byte calendar advanced one second per rtc_tick(), settable from the Modbus
 * time registers (HR 12-14). It mirrors the factory's calendar + advance
 * (`0x2000d850` / `sub_08018bc0`, docs/36): the same field order and the same
 * carry chain, days-in-month and leap-year handling -- so the shared RTC_WALK
 * contract (tests/arm_sim_contract.py) holds identically for both firmwares.
 */
#include <stdint.h>
#include <stdbool.h>

/* 7 contiguous bytes, factory layout: sec, min, hour, day, month, year, weekday.
 * `year` is an offset from 2000 (e.g. 24 = 2024); weekday 0=Sun..6=Sat. */
typedef struct {
    uint8_t sec, minute, hour, day, month, year, weekday;
} inv_rtc_t;

extern inv_rtc_t g_rtc;

bool    rtc_is_leap(uint8_t year);                    /* year offset from 2000 */
uint8_t rtc_days_in_month(uint8_t month, uint8_t year);

/* Advance the calendar by one second, carrying
 * sec->min->hour->day->month->year (days-in-month + leap aware) and recomputing
 * the weekday on a day change. */
void rtc_tick(void);

/* Force the calendar (weekday is recomputed). */
void rtc_set(uint8_t sec, uint8_t minute, uint8_t hour,
             uint8_t day, uint8_t month, uint8_t year);

/* Set from the three Modbus time registers (docs/04):
 *   hr12 = year | (month<<8), hr13 = day | (hour<<8), hr14 = minute | (sec<<8). */
void rtc_set_from_modbus(uint16_t hr12, uint16_t hr13, uint16_t hr14);

/* Minutes-of-day (0..1439) of the current time, for the window evaluators. */
uint16_t rtc_now_minutes(void);

#endif /* INV_RTC_H */
