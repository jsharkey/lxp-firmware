/* Host tests for the OptimalChg_DisChg half-hour schedule lookup (docs/25,
 * docs/modbus-dongle/HR126_131-OptimalChg_DisChg.md).  make test
 *
 * Verifies the pure table-vs-clock logic for HR 126-131: the half-hour slot
 * index, the 8-slots-per-register / 2-bits-per-slot LSB-first packing, the three
 * marks (0 none, 1 charge, 2 discharge), the register boundaries, the midnight
 * edges, and reads that fall outside the table provided.
 */
#include "inv/optchg.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* minutes-of-day from a wall-clock time */
static uint16_t now(int hour, int minute) { return (uint16_t)(60 * hour + minute); }

/* pack eight 2-bit marks into one register, slot 0 in the low bits */
static uint16_t reg_of(const int m[8])
{
    uint16_t r = 0;
    for (int i = 0; i < 8; i++)
        r |= (uint16_t)((m[i] & 0x3) << (2 * i));
    return r;
}

int main(void)
{
    /* --- slot index: each slot is 30 min, 48 across the day ---------------- */
    CHECK(optchg_slot_index(now(0, 0))   == 0,  "00:00 -> slot 0");
    CHECK(optchg_slot_index(now(0, 29))  == 0,  "00:29 -> slot 0");
    CHECK(optchg_slot_index(now(0, 30))  == 1,  "00:30 -> slot 1");
    CHECK(optchg_slot_index(now(3, 30))  == 7,  "03:30 -> slot 7  (last in HR126)");
    CHECK(optchg_slot_index(now(4, 0))   == 8,  "04:00 -> slot 8  (first in HR127)");
    CHECK(optchg_slot_index(now(12, 0))  == 24, "12:00 -> slot 24 (first in HR129)");
    CHECK(optchg_slot_index(now(23, 30)) == 47, "23:30 -> slot 47 (last)");
    CHECK(optchg_slot_index(now(23, 59)) == 47, "23:59 -> slot 47");

    /* --- in-register packing: Time0 is the low 2 bits, Time7 the high 2 ----- */
    { /* HR126 = Time0..7 ; mark Time0=charge, Time2=discharge, Time7=charge */
      int m0[8] = { OPTCHG_CHARGE, 0, OPTCHG_DISCHARGE, 0, 0, 0, 0, OPTCHG_CHARGE };
      uint16_t regs[6] = { reg_of(m0), 0, 0, 0, 0, 0 };
      CHECK(regs[0] == (1u | (2u << 4) | (1u << 14)), "Time0/2/7 pack LSB-first");
      CHECK(optchg_slot_mode(regs, 6, now(0, 0))  == OPTCHG_CHARGE,    "Time0 00:00 charge");
      CHECK(optchg_slot_mode(regs, 6, now(0, 15)) == OPTCHG_CHARGE,    "mid-slot 00:15 charge");
      CHECK(optchg_slot_mode(regs, 6, now(0, 30)) == OPTCHG_NONE,      "Time1 00:30 none");
      CHECK(optchg_slot_mode(regs, 6, now(1, 0))  == OPTCHG_DISCHARGE, "Time2 01:00 discharge");
      CHECK(optchg_slot_mode(regs, 6, now(3, 30)) == OPTCHG_CHARGE,    "Time7 03:30 charge");
      CHECK(optchg_slot_mode(regs, 6, now(3, 59)) == OPTCHG_CHARGE,    "Time7 03:59 charge");
    }

    /* --- register boundary: 03:30-04:00 is HR126.Time7, 04:00- is HR127.Time8 */
    { int m126[8] = { 0,0,0,0,0,0,0, OPTCHG_DISCHARGE };   /* Time7 */
      int m127[8] = { OPTCHG_CHARGE, 0,0,0,0,0,0,0 };      /* Time8 */
      uint16_t regs[6] = { reg_of(m126), reg_of(m127), 0, 0, 0, 0 };
      CHECK(optchg_slot_mode(regs, 6, now(3, 59)) == OPTCHG_DISCHARGE, "03:59 -> HR126.Time7");
      CHECK(optchg_slot_mode(regs, 6, now(4, 0))  == OPTCHG_CHARGE,    "04:00 -> HR127.Time8");
    }

    /* --- last slot lives in HR131.Time47 (bits 14-15) ---------------------- */
    { int m131[8] = { 0,0,0,0,0,0,0, OPTCHG_DISCHARGE };   /* Time47 */
      uint16_t regs[6] = { 0, 0, 0, 0, 0, reg_of(m131) };
      CHECK(optchg_slot_mode(regs, 6, now(23, 30)) == OPTCHG_DISCHARGE, "23:30 -> HR131.Time47");
      CHECK(optchg_slot_mode(regs, 6, now(23, 59)) == OPTCHG_DISCHARGE, "23:59 -> HR131.Time47");
      CHECK(optchg_slot_mode(regs, 6, now(23, 29)) == OPTCHG_NONE,      "23:29 -> HR131.Time46 (none)");
    }

    /* --- midnight: 00:00 is slot 0, never the last slot -------------------- */
    { int first[8] = { OPTCHG_CHARGE, 0,0,0,0,0,0,0 };     /* Time0 */
      int last[8]  = { 0,0,0,0,0,0,0, OPTCHG_DISCHARGE };  /* Time47 */
      uint16_t regs[6] = { reg_of(first), 0, 0, 0, 0, reg_of(last) };
      CHECK(optchg_slot_mode(regs, 6, now(0, 0)) == OPTCHG_CHARGE, "00:00 wraps to Time0, not Time47");
    }

    /* --- an all-none table never marks anything --------------------------- */
    { uint16_t regs[6] = { 0, 0, 0, 0, 0, 0 };
      CHECK(optchg_slot_mode(regs, 6, now(0, 0))   == OPTCHG_NONE, "empty table 00:00 none");
      CHECK(optchg_slot_mode(regs, 6, now(13, 17)) == OPTCHG_NONE, "empty table 13:17 none");
    }

    /* --- reads outside the registers provided clamp to NONE ---------------- */
    { int m0[8] = { OPTCHG_CHARGE, 0,0,0,0,0,0,0 };
      uint16_t one[6] = { reg_of(m0), 0, 0, 0, 0, 0 };
      CHECK(optchg_slot_mode(one, 1, now(0, 0)) == OPTCHG_CHARGE, "n=1 covers HR126 slots");
      CHECK(optchg_slot_mode(one, 1, now(4, 0)) == OPTCHG_NONE,   "n=1 has no HR127 -> none");
      CHECK(optchg_slot_mode(one, 6, 1440)      == OPTCHG_NONE,   "minute 1440 past end -> none");
    }

    printf(g_fail ? "test_optchg: %d/%d FAILED\n" : "test_optchg: %d/%d passed\n",
           g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
