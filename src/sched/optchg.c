/*
 * OptimalChg_DisChg half-hour schedule lookup (see include/inv/optchg.h).
 *
 * Pure, transport-agnostic: given the six packed table registers (HR 126-131)
 * and the current minute-of-day, return the 2-bit mark for the half-hour slot
 * that contains it. Slot si = now_min / 30; its mark is regs[si/8] bits
 * [2*(si%8) + 1 : 2*(si%8)] (8 slots per register, least-significant first), per
 * the EG4 18kPV-12LV Modbus protocol.
 */
#include "inv/optchg.h"

optchg_mode_t optchg_slot_mode(const uint16_t *regs, int n, uint16_t now_min)
{
    int si = optchg_slot_index(now_min);
    if (si < 0 || si >= OPTCHG_NUM_SLOTS)        /* past the end of the day */
        return OPTCHG_NONE;

    int reg = si / OPTCHG_SLOTS_PER_REG;
    if (reg >= n)                                /* slot not in the table given */
        return OPTCHG_NONE;

    int shift = 2 * (si % OPTCHG_SLOTS_PER_REG);
    return (optchg_mode_t)((regs[reg] >> shift) & 0x3u);
}
