/*
 * Skeleton application entry for the open EG4 12000XP com-MCU firmware.
 *
 * This is a FOUNDATION, not a functional replacement yet: it boots, runs the
 * 72 MHz clock init, starts a SysTick heartbeat, and spins. Real subsystems
 * (Modbus-RTU slave, HMI, settings store, fault/state machine) get built out
 * from here against the recovered model in include/inv/.
 */
#include "stm32f103.h"
#include "inv/states.h"
#include "inv/faults.h"
#include "inv/modbus_map.h"
#include "inv/hmi_menu.h"

/* Live system snapshot the future subsystems will share. */
typedef struct {
    inv_state_t state;
    uint32_t    fault_bits;    /* see inv_fault_bit_t */
    uint32_t    warn_bits;     /* see inv_warn_bit_t  */
    uint16_t    input_reg[160];/* Modbus input register image (IR_*)   */
} inv_runtime_t;

static volatile inv_runtime_t g_rt;
static volatile uint32_t g_ticks;

void SysTick_Handler(void) { g_ticks++; }

static void systick_init_1ms(void)
{
    SysTick->LOAD = (SystemCoreClock / 1000U) - 1U;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE | SysTick_CTRL_TICKINT | SysTick_CTRL_ENABLE;
}

int main(void)
{
    /* seed the shared state so the linker keeps the model and it is exercised */
    g_rt.state = STATE_STANDBY;
    g_rt.fault_bits = 0;
    g_rt.warn_bits  = 0;
    g_rt.input_reg[IR_STATE] = (uint16_t)g_rt.state;

    systick_init_1ms();

    for (;;) {
        /* TODO: service Modbus slave, HMI, fault/state machine, DSP link.
         * Placeholder: keep the state register mirror in sync. */
        g_rt.input_reg[IR_STATE] = (uint16_t)g_rt.state;
        (void)MENU__COUNT;  /* HMI menu model is available */
        __asm volatile ("wfi");
    }
}
