/*
 * AC-First load-priority window evaluation (see include/inv/acfirst.h).
 *
 * Pure, transport-agnostic: given the window registers and the current
 * minute-of-day, decide whether any window is active now. Mirrors the factory
 * ARM evaluator sub_080352d0 (docs/25): start-inclusive / end-exclusive, with a
 * midnight-wrap branch, and an empty window (start == end) never active.
 */
#include "inv/acfirst.h"

bool acfirst_window_active(const uint16_t *regs, int n, uint16_t now_min)
{
    for (int i = 0; i < n; i++) {
        uint16_t s = acfirst_reg_minutes(regs[2 * i]);
        uint16_t e = acfirst_reg_minutes(regs[2 * i + 1]);
        if (s == e)                             /* empty / disabled window */
            continue;
        bool in = (s < e) ? (now_min >= s && now_min < e)     /* normal */
                          : (now_min >= s || now_min < e);    /* wraps midnight */
        if (in)
            return true;
    }
    return false;
}
