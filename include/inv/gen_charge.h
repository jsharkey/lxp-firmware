#ifndef INV_GEN_CHARGE_H
#define INV_GEN_CHARGE_H
/*
 * Generator-charge start/stop gate with hysteresis (GenChargeType = "by voltage").
 *
 * The factory decides whether to charge the battery from the generator with a
 * latched voltage hysteresis -- the charge direction (start when the battery is
 * LOW, stop when it is high), the mirror of the discharge gate. Reverse-engineered
 * (T16) on the canonical 07 image (`ceaa-07xx_vE_260214.bin`) as the voltage path
 * of the generator-charge evaluator `sub_08035050` -- the block
 * `0x08035086 … 0x080350dc`, verdict byte `0x2000dbc0`:
 *
 *     v = (uint16 safety-bank battery voltage @+0x0a) / 10       // signed divide
 *     if (!active) active = (v <  start_v);                      // start charging when low
 *     else         active = !(v >= end_v && stop_ok);            // stop only when high AND confirmed
 *
 * `start_v` is HR 194 GenChgStartVolt (settings `+0xac`), `end_v` is HR 195
 * GenChgEndVolt (settings `+0xae`); both 0.1 V, compared to the battery voltage
 * divided by 10 (matching the factory's signed divide). The **stop** also requires
 * two DSP/safety-bank status bits -- `bank+0xb6` bit 11 AND `bank+0xbc` bit 15
 * (`stop_ok`) -- so the generator keeps charging until the system confirms it is
 * safe to drop it. Mode is selected by HR 120 bit 7 GenChargeType (settings `+0x33`
 * bit 7): 0 = by voltage (this), 1 = by SOC (HR 196/197, settings `+0xb0`; the SOC
 * sibling, verdict `0x2000dbc1`). The thresholds are also pushed to the DSP config
 * (block 6, T10). See docs/wiring/ARM-UART5-dongle/HR194_198-generator-charge.md.
 *
 * Pure and host-testable: the caller holds the latch and supplies the bank voltage,
 * the two thresholds and the `stop_ok` confirmation.
 */
#include <stdint.h>
#include <stdbool.h>

/*
 * One hysteresis step of the generator-charge-by-voltage gate.
 *   active     - previous latched verdict (false = generator-charge off)
 *   vbat_bank  - battery voltage as the safety bank stores it (u16, 0.1 V, +0x0a);
 *                divided by 10 before comparison, matching the factory.
 *   start_v    - turn-ON threshold (HR 194 / settings +0xac), charge when v < start_v
 *   end_v      - turn-OFF threshold (HR 195 / settings +0xae), stop when v >= end_v
 *   stop_ok    - the DSP confirmation for stopping (bank+0xb6 bit11 AND bank+0xbc
 *                bit15); the gate will not turn off until this is true.
 * Returns the new latched verdict.
 */
bool inv_gen_charge_volt_gate(bool active, uint16_t vbat_bank,
                              uint16_t start_v, uint16_t end_v, bool stop_ok);

/*
 * One hysteresis step of the generator-charge-by-SOC gate (GenChargeType = 1).
 * The SOC sibling of the voltage gate: the SAME charge-direction hysteresis, on the
 * battery state-of-charge byte instead of voltage. RE-pinned (T16) on the canonical
 * 07 image as the self-contained block `0x08035198…0x080351de`, verdict byte
 * `0x2000dbc1` (the sibling of the voltage verdict `0x2000dbc0`):
 *
 *     if (!active) active = (soc <  start_soc);                  // start charging when LOW
 *     else         active = !(soc >= end_soc && stop_ok);        // stop only when HIGH AND confirmed
 *
 * The factory reads the battery SOC byte (relayed struct `0x2000d7b0+0`) and compares
 * it UNSIGNED (blo/bhs) against two 1-byte thresholds: `start_soc` is HR 196
 * GenChgStartSOC (settings `+0xb0`), `end_soc` is HR 197 GenChgEndSOC (settings
 * `+0xb1`) -- the low/high bytes of the `+0xb0` halfword. The **stop** requires the
 * same DSP confirmation as the voltage gate (`bank+0xb6` bit 11 AND `bank+0xbc`
 * bit 15), passed as `stop_ok`. Pure/latched like the voltage gate.
 *   active     - previous latched verdict (false = generator-charge off)
 *   soc        - battery state of charge, 0-100 (%)
 *   start_soc  - turn-ON threshold  (HR 196 / settings +0xb0), charge when soc < start_soc
 *   end_soc    - turn-OFF threshold (HR 197 / settings +0xb1), stop when soc >= end_soc
 *   stop_ok    - the DSP confirmation for stopping; the gate will not turn off until true
 */
bool inv_gen_charge_soc_gate(bool active, uint8_t soc,
                             uint8_t start_soc, uint8_t end_soc, bool stop_ok);

/*
 * Combined generator-charge controller (T16): selects the by-voltage or by-SOC gate
 * per GenChargeType (HR 120 bit 7, settings `+0x33` bit 7) and returns whether the
 * generator should be charging the battery now. Both gates are stepped every call so
 * their latches stay warm across a mode change; the returned verdict is:
 *   charge_type 0 (by voltage) -> the voltage gate's verdict (0x2000dbc0)
 *   charge_type 1 (by SOC)     -> the SOC gate's verdict     (0x2000dbc1)
 * Mirrors the mode select in the factory `sub_08035050` (HR 120 bit 7). Each
 * underlying gate is factory-verified (above); stepping both latches every call is
 * ours' composition (the factory evaluates only the selected path, and force-clears
 * the voltage verdict while in SOC mode) and is not itself separately oracle-pinned.
 */
typedef struct {
    bool v_active;   /* latched by-voltage verdict (0x2000dbc0) */
    bool s_active;   /* latched by-SOC verdict     (0x2000dbc1) */
} inv_gen_charge_state_t;

bool inv_gen_charge_permit(inv_gen_charge_state_t *st, bool charge_by_soc,
                           uint16_t vbat_bank, uint16_t v_start, uint16_t v_end,
                           uint8_t soc, uint8_t s_start, uint8_t s_end,
                           bool stop_ok);

#endif /* INV_GEN_CHARGE_H */
