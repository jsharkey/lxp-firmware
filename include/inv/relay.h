/*
 * relay — AC transfer-relay control (grid/EPS contactors).
 * See src/relay.c and tests/test_arm_sim.py (factory parity).
 */
#ifndef INV_RELAY_H
#define INV_RELAY_H

#include <stdint.h>
#include <stdbool.h>

/* Configure the transfer-relay GPIOs (PA12, PB3) as outputs. */
void relay_init(void);

/*
 * Normal-mode AC-transfer decision (T14). Reverse-engineered from the factory
 * relay function `sub_08018a7c` (grid-eval path) on the canonical 07 image: once
 * the AC-transfer feature is *enabled*, PB3 (transfer contactor B) closes and PA12
 * (contactor A, the grid-connect side) opens when the DSP reports the grid is
 * qualified, else closes. While the feature is disabled both open.
 *
 *   enabled == false            -> PA12 = 0, PB3 = 0   (both open)
 *   enabled == true, grid ok    -> PA12 = 0, PB3 = 1
 *   enabled == true, grid NOT ok-> PA12 = 1, PB3 = 1
 *
 * `enabled` is the factory enable gate (`0x2000d9ca` bit 3 OR `0x2000d810` bit 4;
 * derived by `sub_0801887c` — see docs/18). `dsp_grid` is the DSP grid-status word
 * (`0x2000ce5c + 0xbc`): the grid is qualified iff **bit 20 is set AND bits 29-30
 * != 2** (an additional internal disqualifier, `0x2000d810` bit 4, is assumed
 * clear here). The real switching is staged behind three 50-tick debounces
 * (`0x2000dba4/5/6`, break-before-make) — this is the settled steady-state verdict;
 * the debounce timing is a separate layer (docs/18). Pure/host-testable.
 */
void inv_ac_transfer_decide(bool enabled, uint32_t dsp_grid,
                            bool *pa12, bool *pb3);

/* Manual/AutoTest override: in manual mode the command word drives the AC
 * transfer relays directly -- PA12 <- bit 1, PB3 <- bit 0. Mirrors the factory
 * grid-protection self-test (docs/18). */
void relay_set_override(uint16_t cmd, int manual);

/* Set the current operating mode (IR_STATE, inv/states.h). In normal operation
 * the run-enable relay (PC6) follows it: closed when running, open in
 * standby/fault/programming. */
void relay_set_mode(uint8_t ir_state);

/* Apply the current relay state (call periodically). */
void relay_poll(void);

#endif /* INV_RELAY_H */
