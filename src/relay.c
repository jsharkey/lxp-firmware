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
 * The normal working-mode AC-transfer decision (grid-eval path, sub_08018a7c) is
 * reimplemented as the pure inv_ac_transfer_decide() below (T14, docs/18); its
 * steady-state verdict is factory-verified (tests/test_ac_transfer.py). The run-
 * enable relay (PC6) follows IR_STATE in relay_poll().
 */
#include "stm32f103.h"
#include "inv/relay.h"

/* Grid-qualified per the DSP grid-status word (0x2000ce5c+0xbc): bit 20 set and
 * bits 29-30 != 2 (sub_08018a7c grid-eval, 07 image). */
#define DSP_GRID_OK_BIT     (1u << 20)
#define DSP_GRID_MODE_SHIFT 29
#define DSP_GRID_MODE_MASK  0x3u
#define DSP_GRID_MODE_BAD   2u

void inv_ac_transfer_decide(bool enabled, bool dsp_force, uint32_t dsp_grid,
                            bool *pa12, bool *pb3)
{
    if (dsp_force) {                 /* DSP "transfer to backup": force both closed */
        if (pa12) *pa12 = true;
        if (pb3)  *pb3  = true;
        return;
    }
    if (!enabled) {                 /* feature disabled: both contactors open */
        if (pa12) *pa12 = false;
        if (pb3)  *pb3  = false;
        return;
    }
    bool grid_ok = (dsp_grid & DSP_GRID_OK_BIT) &&
                   (((dsp_grid >> DSP_GRID_MODE_SHIFT) & DSP_GRID_MODE_MASK) != DSP_GRID_MODE_BAD);
    if (pb3)  *pb3  = true;          /* transfer contactor B closes when enabled */
    if (pa12) *pa12 = !grid_ok;      /* contactor A opens when the grid is qualified */
}

#define RELAY_PA12  (1u << 12)   /* GPIOA12 - AC transfer relay A */
#define RELAY_PB3   (1u << 3)    /* GPIOB3  - AC transfer relay B */
#define RELAY_PC6   (1u << 6)    /* GPIOC6  - inverter run-enable / bypass relay */

#define STATE_PROGRAMMING 0x02   /* inv_state_t: <=this => not running (standby/fault/prog) */

static uint16_t s_override_cmd;
static uint8_t  s_manual;
static uint8_t  s_mode;          /* operating mode = IR_STATE (inv/states.h) */

/* Live AC-transfer inputs (T14 wiring): the ARM-local enable, the DSP force bit, and
 * the DSP grid-status word. Default disabled -> both transfer contactors open. */
static bool     s_transfer_enabled;
static bool     s_transfer_force;
static uint32_t s_transfer_grid;

void relay_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPBEN | RCC_APB2ENR_IOPCEN;
    /* PA12 = output push-pull 50MHz (CRH nibble for pin 12) */
    GPIOA->CRH = (GPIOA->CRH & ~0x000F0000u) | 0x00030000u;
    /* PB3  = output push-pull 50MHz (CRL nibble for pin 3) */
    GPIOB->CRL = (GPIOB->CRL & ~0x0000F000u) | 0x00003000u;
    /* PC6  = output push-pull 50MHz (CRL nibble for pin 6) */
    GPIOC->CRL = (GPIOC->CRL & ~0x0F000000u) | 0x03000000u;
}

void relay_set_override(uint16_t cmd, int manual)
{
    s_override_cmd = cmd;
    s_manual = manual ? 1u : 0u;
}

void relay_set_mode(uint8_t ir_state)
{
    s_mode = ir_state;
}

void relay_set_transfer_inputs(bool enabled, bool dsp_force, uint32_t dsp_grid)
{
    s_transfer_enabled = enabled;
    s_transfer_force   = dsp_force;
    s_transfer_grid    = dsp_grid;
}

void relay_poll(void)
{
    if (s_manual) {                 /* manual / AutoTest override drives the transfer relays */
        if (s_override_cmd & 0x2u) GPIOA->BSRR = RELAY_PA12; else GPIOA->BRR = RELAY_PA12;
        if (s_override_cmd & 0x1u) GPIOB->BSRR = RELAY_PB3;  else GPIOB->BRR = RELAY_PB3;
        return;
    }
    /* normal operation: the run-enable relay follows the operating mode --
     * closed once the inverter is in a running state, open in standby/fault/
     * programming (factory sub_08016ec6 gate on IR_STATE; docs/18). */
    if (s_mode > STATE_PROGRAMMING) GPIOC->BSRR = RELAY_PC6;
    else                            GPIOC->BRR = RELAY_PC6;

    /* AC transfer pair (PA12/PB3): the grid-eval decision (T14), driven from the
     * live inputs fed by the main loop. Default inputs leave both contactors open. */
    bool pa12, pb3;
    inv_ac_transfer_decide(s_transfer_enabled, s_transfer_force, s_transfer_grid,
                           &pa12, &pb3);
    if (pa12) GPIOA->BSRR = RELAY_PA12; else GPIOA->BRR = RELAY_PA12;
    if (pb3)  GPIOB->BSRR = RELAY_PB3;  else GPIOB->BRR = RELAY_PB3;
}
