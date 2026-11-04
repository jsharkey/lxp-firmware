/*
 * relay — AC transfer-relay control.
 *
 * The factory drives two AC transfer contactors on PA12 and PB3 (docs/16,
 * docs/18). Reimplemented here is the manual / grid-protection-self-test
 * override path: in test mode a command word drives the relays directly --
 * PA12 <- bit 1, PB3 <- bit 0 -- and is ignored otherwise. Validated against
 * the factory image by
 * tests/test_arm_sim.py::test_relay_override_drives_transfer_pins.
 *
 * (The normal, working-mode-driven relay behaviour -- IR_STATE + grid status,
 * docs/18 -- is a separate piece still to be reimplemented.)
 */
#include "stm32f103.h"
#include "inv/relay.h"

#define RELAY_PA12  (1u << 12)   /* GPIOA12 - AC transfer relay A */
#define RELAY_PB3   (1u << 3)    /* GPIOB3  - AC transfer relay B */

static uint16_t s_override_cmd;
static uint8_t  s_manual;

void relay_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPBEN;
    /* PA12 = output push-pull 50MHz (CRH nibble for pin 12) */
    GPIOA->CRH = (GPIOA->CRH & ~0x000F0000u) | 0x00030000u;
    /* PB3  = output push-pull 50MHz (CRL nibble for pin 3) */
    GPIOB->CRL = (GPIOB->CRL & ~0x0000F000u) | 0x00003000u;
}

void relay_set_override(uint16_t cmd, int manual)
{
    s_override_cmd = cmd;
    s_manual = manual ? 1u : 0u;
}

void relay_poll(void)
{
    if (!s_manual)
        return;                      /* only drive in manual / test mode */
    if (s_override_cmd & 0x2u) GPIOA->BSRR = RELAY_PA12; else GPIOA->BRR = RELAY_PA12;
    if (s_override_cmd & 0x1u) GPIOB->BSRR = RELAY_PB3;  else GPIOB->BRR = RELAY_PB3;
}
