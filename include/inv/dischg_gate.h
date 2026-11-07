#ifndef INV_DISCHG_GATE_H
#define INV_DISCHG_GATE_H
/*
 * Discharge-control voltage gate with hysteresis (DischgCtrlType = "by voltage").
 *
 * The factory evaluates a battery-voltage threshold with a deadband to decide
 * whether battery discharge is currently allowed, and latches the verdict so it
 * does not chatter at the boundary. Reverse-engineered from the ceaa05/`com_flat`
 * ARM evaluator `sub_0801ed28` (T15), whose voltage path is exactly:
 *
 *     v = (uint16 safety-bank battery voltage @+0x0a) / 10      // signed divide
 *     active = active ? (v >= stop) : (v >= start)              // latched hysteresis
 *
 * i.e. turn **on** once V reaches `start` (settings `+0x46`), stay on until V
 * falls **below** `stop` (settings `+0x48`), then turn off. The verdict byte
 * (`0x2000aa5f`) is consumed by the main power-control function `sub_0801f438`.
 * Mode is selected by HR 120 DischgCtrlType (settings `+0x33` bits 4-5): 0 = by
 * voltage (this), 1 = by SOC (battery-limit struct `0x2000a68c`, needs T11),
 * 2 = both (voltage OR SOC). Gated by the discharge master-enable settings `+0x23`
 * bit 13. See docs/41-charge-discharge-schedule-gates.md.
 *
 * Pure and transport-agnostic (host-testable): the caller holds the latch and
 * feeds the raw safety-bank voltage word and the two thresholds.
 */
#include <stdint.h>
#include <stdbool.h>

/*
 * One hysteresis step of the discharge-by-voltage gate.
 *   active      - the previous latched verdict (false = discharge gate open)
 *   vbat_bank   - battery voltage as the safety bank stores it (u16, 0.1 V),
 *                 bank offset +0x0a (= IR 107); divided by 10 before comparison,
 *                 matching the factory's signed divide.
 *   start_v     - turn-ON threshold (settings +0x46), in the divided units
 *   stop_v      - turn-OFF threshold (settings +0x48), in the divided units
 * Returns the new latched verdict: on when v >= start_v (from off), off when
 * v < stop_v (from on). With start_v > stop_v this is a deadband; the comparison
 * is signed, as in the factory.
 */
bool inv_dischg_volt_gate(bool active, uint16_t vbat_bank,
                          uint16_t start_v, uint16_t stop_v);

#endif /* INV_DISCHG_GATE_H */
