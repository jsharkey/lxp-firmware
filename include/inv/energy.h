/*
 * Accumulated energy counters (Modbus input registers IR 28-37 daily, IR 40-59
 * cumulative; 0.1 kWh). Clean-room reimplementation of the factory accumulator.
 *
 * Mechanism, recovered from the factory 07-series image (accumulator functions
 * 0x0801fbc4 / 0x0801f960, served by the input getter 0x0803289c; struct at
 * factory RAM 0x20009954) and validated by live capture
 * (tests/test_energy.py / energy_contract.py), docs/37:
 *
 *   per accumulation tick, for each channel, GATED on an operational state:
 *       sub[ch] += power[ch] >> 1;                  // integrate (half-rate)
 *       if (sub[ch] >= 3600001) {                   // crossed 0.1 kWh quantum
 *           day[ch]++;  all[ch]++;  sub[ch] -= 3600000;
 *       }
 *
 * The instantaneous power[ch] is telemetry the ARM receives (PV power from the
 * DSP/safety-CPU link, etc.) -- the accumulation is tick/power driven, while the
 * RTC drives only the daily reset (energy_rollover). The cumulative counters
 * persist; the daily counters reset at the day boundary.
 */
#ifndef INV_ENERGY_H
#define INV_ENERGY_H

#include <stdint.h>

#define ENERGY_NCH      10          /* Epv1/2/3, Einv, Erec, Echg, Edischg, Eeps, Etogrid, Etouser */
#define ENERGY_THRESHOLD 3600001u   /* sub-accumulator level that yields one 0.1 kWh count */
#define ENERGY_STEP      3600000u   /* amount subtracted back after each count */
#define ENERGY_RUN_STATE 3u         /* op-state >= this => running => accumulate (factory bank>=3) */

typedef struct {
    uint32_t sub[ENERGY_NCH];       /* integration sub-accumulator (energy below one quantum) */
    uint16_t day[ENERGY_NCH];       /* daily counter (0.1 kWh), reset at midnight             */
    uint32_t all[ENERGY_NCH];       /* cumulative counter (0.1 kWh), persists                 */
    uint32_t pwr[ENERGY_NCH];       /* instantaneous power source, fed from telemetry         */
    uint8_t  last_day;              /* last RTC day-of-month seen (for the daily rollover)     */
    uint8_t  day_valid;             /* last_day has been initialised                          */
} energy_t;

extern energy_t g_energy;

/* Set a channel's instantaneous power (the loop feeds this from telemetry). */
void energy_set_power(uint8_t ch, uint32_t watts);

/* One accumulation tick. `op_state` is the classified operating state (IR_STATE);
 * accumulation only runs when it indicates a running mode (>= ENERGY_RUN_STATE),
 * matching the factory's gate. */
void energy_tick(uint8_t op_state);

/* Daily rollover: if `rtc_day` (RTC day-of-month) differs from the last tick's,
 * zero all daily counters (the cumulative counters are left untouched). */
void energy_rollover(uint8_t rtc_day);

/* Clear the cumulative counters (HR 11 EnergyRecordClr); also clears daily + sub. */
void energy_reset_all(void);

/* Publish the counters into a Modbus input-register image (>= 60 entries): the
 * daily counters to IR 28-37 and the cumulative 32-bit pairs to IR 40-59. */
void energy_publish(uint16_t *input_reg);

#endif /* INV_ENERGY_H */
