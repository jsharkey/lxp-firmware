/*
 * Accumulated energy counters. See inv/energy.h and docs/37.
 * Faithful to the factory accumulator: integrate power>>1 per tick, emit one
 * 0.1 kWh count each time the sub-accumulator crosses 3,600,001, gated on a
 * running operating state. The RTC drives only the daily reset.
 */
#include "inv/energy.h"
#include "inv/modbus_map.h"

energy_t g_energy;

void energy_set_power(uint8_t ch, uint32_t watts)
{
    if (ch < ENERGY_NCH) g_energy.pwr[ch] = watts;
}

void energy_tick(uint8_t op_state)
{
    if (op_state < ENERGY_RUN_STATE) return;        /* not running -> no accumulation */
    for (uint8_t ch = 0; ch < ENERGY_NCH; ch++) {
        g_energy.sub[ch] += g_energy.pwr[ch] >> 1;  /* half-rate integration (factory) */
        if (g_energy.sub[ch] >= ENERGY_THRESHOLD) {
            g_energy.day[ch]++;
            g_energy.all[ch]++;
            g_energy.sub[ch] -= ENERGY_STEP;
        }
    }
}

void energy_rollover(uint8_t rtc_day)
{
    if (!g_energy.day_valid) {                       /* first observation: latch, don't reset */
        g_energy.last_day = rtc_day;
        g_energy.day_valid = 1;
        return;
    }
    if (rtc_day != g_energy.last_day) {              /* crossed a day boundary */
        for (uint8_t ch = 0; ch < ENERGY_NCH; ch++) g_energy.day[ch] = 0;
        g_energy.last_day = rtc_day;
    }
}

void energy_reset_all(void)
{
    for (uint8_t ch = 0; ch < ENERGY_NCH; ch++) {
        g_energy.sub[ch] = 0;
        g_energy.day[ch] = 0;
        g_energy.all[ch] = 0;
    }
}

void energy_publish(uint16_t *ir)
{
    /* daily reg = 28 + ch; cumulative L/H = 40 + 2*ch / 41 + 2*ch (docs/37) */
    for (uint8_t ch = 0; ch < ENERGY_NCH; ch++) {
        ir[IR_EPV1_DAY + ch]        = g_energy.day[ch];
        ir[IR_EPV1_ALL_L + 2 * ch]  = (uint16_t)(g_energy.all[ch] & 0xFFFF);
        ir[IR_EPV1_ALL_L + 2 * ch + 1] = (uint16_t)(g_energy.all[ch] >> 16);
    }
}
