/*
 * relay — AC transfer-relay control (grid/EPS contactors).
 * See src/relay.c and tests/test_arm_sim.py (factory parity).
 */
#ifndef INV_RELAY_H
#define INV_RELAY_H

#include <stdint.h>

/* Configure the transfer-relay GPIOs (PA12, PB3) as outputs. */
void relay_init(void);

/* Manual/AutoTest override: in manual mode the command word drives the AC
 * transfer relays directly -- PA12 <- bit 1, PB3 <- bit 0. Mirrors the factory
 * grid-protection self-test (docs/18). */
void relay_set_override(uint16_t cmd, int manual);

/* Apply the current relay state (call periodically). */
void relay_poll(void);

#endif /* INV_RELAY_H */
