/*
 * gpio_sample — observable GPIO behaviours recovered from the factory image,
 * reimplemented so our firmware matches it pin-for-pin. The parity tests in
 * tests/test_arm_sim.py assert these against the factory oracle via
 * tools/arm_sim.py.
 *
 * pb7_sample_poll(): mirror of factory sub_0802e452. PB7 is the board's
 * bit-banged line (see docs/16-arm-io-map.md; its exact protocol is still being
 * decoded, docs/18-power-path-relays.md). The factory debounces PB7 as an INPUT
 * by sampling it 10 times and, when the majority (>=6) read high, latches the
 * state and drives PB7 HIGH. We reproduce that observable contract here.
 */
#include "stm32f103.h"
#include "inv/gpio_sample.h"

#define PB7_MASK   (1U << 7)
#define PB7_SAMPLES 10
#define PB7_MAJORITY 6

static uint8_t s_pb7_latched;   /* 1 once a majority-high sample has latched */

void pb7_sample_poll(void)
{
    int high = 0;
    for (int i = 0; i < PB7_SAMPLES; i++)
        if (GPIOB->IDR & PB7_MASK)
            high++;

    if (high >= PB7_MAJORITY) {
        s_pb7_latched = 1;
        GPIOB->BSRR = PB7_MASK;      /* drive PB7 high */
    } else {
        s_pb7_latched = 0;
    }
}

int pb7_latched(void)
{
    return s_pb7_latched;
}
