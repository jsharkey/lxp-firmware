#ifndef INV_DISCHG_GATE_H
#define INV_DISCHG_GATE_H
/*
 * Discharge-control voltage gate with hysteresis (DischgCtrlType = "by voltage").
 *
 * The factory evaluates a battery-voltage threshold with a deadband to decide
 * whether battery discharge is currently allowed, and latches the verdict so it
 * does not chatter at the boundary. Reverse-engineered (T15) on the canonical 07
 * image (`ceaa-07xx_vE_260214.bin`) as the voltage path of the discharge-gate
 * evaluator — the self-contained block `0x080355c2…0x08035608`, verdict byte
 * `0x2000dbc3` — whose decision is exactly:
 *
 *     v = (uint16 safety-bank battery voltage @+0x0a) / 10      // signed divide
 *     active = active ? (v >= stop) : (v >= start)              // latched hysteresis
 *
 * i.e. turn **on** once V reaches `start` (settings `+0x46`), stay on until V
 * falls **below** `stop` (settings `+0x48`), then turn off. Mode is selected by
 * HR 120 DischgCtrlType (settings `+0x33` bits 4-5): 0 = by voltage (this),
 * 1 = by SOC (battery-limit struct, needs T11), 2 = both. The verdict is consumed
 * by the main power-control function. (The 05-series image has the identical logic
 * at `sub_0801ed28` / verdict `0x2000aa5f`.) See
 * docs/41-charge-discharge-schedule-gates.md.
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

/*
 * One hysteresis step of the discharge-by-SOC gate (DischgCtrlType = 1, "by SOC").
 * The SOC sibling of the voltage gate: the SAME latched hysteresis, on the battery
 * state-of-charge byte instead of voltage. RE-pinned (T15) on the canonical 07
 * image as the self-contained block `0x08035616…0x08035662` whose verdict byte is
 * `0x2000dbc4` (the sibling of the voltage verdict `0x2000dbc3`):
 *
 *     active = active ? (soc >= stop_soc) : (soc >= start_soc)   // unsigned bytes
 *
 * turn **on** once SOC reaches `start_soc` (settings `+0x4a`), stay on until SOC
 * falls **below** `stop_soc` (settings `+0x4b`), then turn off. The
 * factory compares the battery SOC byte (relayed struct `0x2000d7b0+0`) unsigned
 * (blo/bhs) against the two 1-byte thresholds. Pure/latched like the voltage gate.
 *   active     - previous latched verdict (false = discharge gate open)
 *   soc        - battery state of charge, 0-100 (%)
 *   start_soc  - turn-ON threshold  (settings +0x4a)
 *   stop_soc   - turn-OFF threshold (settings +0x4b); start_soc > stop_soc = deadband
 */
bool inv_dischg_soc_gate(bool active, uint8_t soc,
                         uint8_t start_soc, uint8_t stop_soc);

/*
 * Combined discharge-permit controller (T15): selects the by-voltage and/or
 * by-SOC gate per DischgCtrlType (HR 120 bits 4-5) and returns whether battery
 * discharge is currently permitted. Both gates are stepped every call so their
 * latches stay warm across a mode change; the returned permit is:
 *   ctrl_type 0 (by voltage) -> the voltage gate's verdict
 *   ctrl_type 1 (by SOC)     -> the SOC gate's verdict
 *   ctrl_type 2 (both)       -> voltage AND SOC
 * The two gates are each factory-verified (above); the mode-2 "both" combination
 * is ours' composition (AND) and is NOT separately oracle-pinned to the factory's
 * combined sub-verdict (0x2000dbc5/c6) — see docs/41.
 */
typedef struct {
    bool v_active;   /* latched by-voltage verdict */
    bool s_active;   /* latched by-SOC verdict     */
} inv_dischg_state_t;

bool inv_dischg_permit(inv_dischg_state_t *st, uint8_t ctrl_type,
                       uint16_t vbat_bank, uint16_t v_start, uint16_t v_stop,
                       uint8_t soc, uint8_t s_start, uint8_t s_stop);

#endif /* INV_DISCHG_GATE_H */
