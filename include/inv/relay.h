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
 *   dsp_force == true           -> PA12 = 1, PB3 = 1   (DSP "transfer to backup")
 *   enabled == false            -> PA12 = 0, PB3 = 0   (both open)
 *   enabled == true, grid ok    -> PA12 = 0, PB3 = 1
 *   enabled == true, grid NOT ok-> PA12 = 1, PB3 = 1
 *
 * `enabled` is the ARM-local enable gate (`0x2000d9ca` bit 3 OR `0x2000d810` bit 4;
 * derived by `sub_0801887c` — see docs/18). `dsp_force` is the DSP-provided bit
 * `0x2000ce5c + 0xca` bit 4: it is a THIRD enable source that **also forces the
 * transfer state (PA12=1/PB3=1) regardless of the grid word** — the DSP's "transfer
 * to backup" command (factory-verified, `test_factory_dsp_bit_forces_transfer`), so
 * it is checked first. `dsp_grid` is the DSP grid-status word (`0x2000ce5c + 0xbc`):
 * the grid is qualified iff **bit 20 is set AND bits 29-30 != 2**. The real switching
 * is staged behind three 50-tick debounces (`0x2000dba4/5/6`, break-before-make) —
 * this is the settled steady-state verdict; the debounce timing is a separate layer
 * (docs/18). Pure/host-testable.
 */
void inv_ac_transfer_decide(bool enabled, bool dsp_force, uint32_t dsp_grid,
                            bool *pa12, bool *pb3);

/*
 * Feed the live AC-transfer inputs for relay_poll() to act on in normal mode
 * (T14 live wiring). `enabled` is the ARM-local enable (no confirmed source in ours
 * yet — its provenance is open, docs/18 — so it is normally false), `dsp_force` is
 * the safety bank's `+0xca` bit 4 (decoded by our USART2 RX), and `dsp_grid` is the
 * bank dword `+0xbc` (not yet in our tag decode — reads 0 until that lands, a
 * T05/T09 follow-on). relay_poll() drives PA12/PB3 from inv_ac_transfer_decide() on
 * these, except in manual-override mode.
 */
void relay_set_transfer_inputs(bool enabled, bool dsp_force, uint32_t dsp_grid);

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
