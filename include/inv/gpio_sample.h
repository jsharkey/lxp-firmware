/*
 * gpio_sample — observable GPIO behaviours mirrored from the factory image.
 * See src/gpio_sample.c and tests/test_arm_sim.py (parity tests).
 */
#ifndef INV_GPIO_SAMPLE_H
#define INV_GPIO_SAMPLE_H

/* Debounce-sample PB7 (10x); on a majority-high reading, latch and drive PB7
 * high. Mirrors factory sub_0802e452. */
void pb7_sample_poll(void);

/* Last latched PB7 state (1 = majority-high). */
int pb7_latched(void);

#endif /* INV_GPIO_SAMPLE_H */
