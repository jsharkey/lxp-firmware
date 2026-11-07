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

#endif /* INV_GEN_CHARGE_H */
