#ifndef INV_OPTCHG_H
#define INV_OPTCHG_H
/*
 * OptimalChg_DisChg half-hour charge/discharge schedule vs. the real-time clock.
 *
 * Modbus holding registers 126-131 (HR_OPTCHG_TABLE_*) carry a 48-slot x 2-bit
 * table: one mark per half-hour of the day. Slot k covers minutes [30k, 30k+30)
 * -- Time0 = 00:00-00:30, ... Time47 = 23:30-00:00 -- and each mark is
 *   0 = no action, 1 = charging, 2 = discharging.
 * The marks are packed 8 per register, two bits each, least-significant first:
 * slot si lives in regs[si/8] bits [2*(si%8) + 1 : 2*(si%8)], so HR 126 holds
 * Time0 (bits 0-1) .. Time7 (bits 14-15), HR 127 holds Time8..Time15, and so on.
 * (Layout per the EG4 18kPV-12LV Modbus protocol; see
 * docs/wiring/ARM-UART5-dongle/HR126_131-OptimalChg_DisChg.md.)
 *
 * The ARM would look up the current slot's mark against the clock, like the
 * AC-First windows (inv/acfirst.h). NOTE: the ceaa-07xx factory image does NOT
 * evaluate this table at all -- it is stored and read back over Modbus but never
 * consumed (dormant; see docs/31 Q5 and docs/wiring/ARM-UART5-dongle/HR126_131). To stay
 * behaviour-compatible with the factory oracle, this evaluator is intentionally
 * NOT wired into the main loop; it exists as a pure, host-testable helper (and a
 * ready implementation should a later image activate the feature).
 */
#include <stdint.h>

#define OPTCHG_NUM_SLOTS 48          /* 48 half-hour slots in a day            */
#define OPTCHG_NUM_REGS  6           /* 8 slots per register -> 6 registers    */
#define OPTCHG_SLOTS_PER_REG 8

typedef enum {
    OPTCHG_NONE      = 0,            /* no action this half-hour               */
    OPTCHG_CHARGE    = 1,            /* charge this half-hour                  */
    OPTCHG_DISCHARGE = 2             /* discharge this half-hour               */
} optchg_mode_t;

/* Slot index (0..47) covering a minute-of-day (0..1439); each slot is 30 min. */
static inline int optchg_slot_index(uint16_t now_min)
{
    return now_min / 30;
}

/*
 * The 2-bit mark for the half-hour slot that contains now_min (minutes-of-day),
 * read from the `n`-register table (regs[0] = HR 126 .. regs[5] = HR 131).
 * Returns OPTCHG_NONE when the slot falls outside the registers provided
 * (now_min >= 1440, or the owning register is beyond `n`). The returned value is
 * the raw 2-bit field; the spec defines only 0/1/2.
 */
optchg_mode_t optchg_slot_mode(const uint16_t *regs, int n, uint16_t now_min);

#endif /* INV_OPTCHG_H */
