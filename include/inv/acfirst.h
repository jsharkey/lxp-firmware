#ifndef INV_ACFIRST_H
#define INV_ACFIRST_H
/*
 * AC-First load-priority time windows vs. the real-time clock.
 *
 * The three AC-First windows (Modbus holding registers 152-157, HR_ACFIRST_*)
 * are each a packed u16 = (minute<<8)|hour (docs/08, docs/25). The ARM owns the
 * clock and evaluates "is the current time inside any AC-First window now?"
 * against it; the factory surfaces that verdict as bit 8 of input register 126
 * (IR_ACFIRST_STATUS / IR_ACFIRST_WIN_ACTIVE -- docs/25). These are the pure,
 * host-testable pieces of that evaluation; main.c wires them to the register
 * image and the loop.
 */
#include <stdint.h>
#include <stdbool.h>

#define ACFIRST_NUM_WINDOWS 3

/* Minutes-of-day (0..1439) from a packed window register u16 = (minute<<8)|hour. */
static inline uint16_t acfirst_reg_minutes(uint16_t reg)
{
    return (uint16_t)(60u * (reg & 0xFFu) + (reg >> 8));
}

/* Minutes-of-day from the Modbus time registers: HR_TIME_DATE_HOUR packs
 * date|(hour<<8), HR_TIME_MIN_SEC packs minute|(sec<<8) (docs/04). */
static inline uint16_t acfirst_clock_minutes(uint16_t hr_date_hour,
                                             uint16_t hr_min_sec)
{
    return (uint16_t)(60u * (hr_date_hour >> 8) + (hr_min_sec & 0xFFu));
}

/*
 * True iff now_min (minutes-of-day) falls inside any of the `n` {start,end}
 * window pairs in `regs` (regs[2i] = start, regs[2i+1] = end, each packed
 * u16 = (minute<<8)|hour). The test is start-inclusive, end-exclusive
 * (start <= now < end), with midnight wrap when start > end; an empty window
 * (start == end) is never active. Mirrors the factory evaluator sub_080352d0.
 */
bool acfirst_window_active(const uint16_t *regs, int n, uint16_t now_min);

#endif /* INV_ACFIRST_H */
