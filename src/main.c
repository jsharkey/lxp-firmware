/*
 * Skeleton application entry for the open EG4 12000XP com-MCU firmware.
 *
 * Boots, runs the 72 MHz clock init, starts a 1 ms SysTick, and services the
 * Modbus-RTU slave against a shared runtime model. The remaining subsystems
 * (HMI, settings store, fault/state machine, DSP link) build out from here.
 */
#include "stm32f103.h"
#include "inv/states.h"
#include "inv/faults.h"
#include "inv/modbus.h"
#include "inv/modbus_map.h"
#include "inv/hmi.h"
#include "inv/hmi_menu.h"

/* Shared system snapshot the subsystems read/write. */
typedef struct {
    uint16_t input_reg[160];    /* Modbus input-register image (IR_*)   */
    uint16_t holding_reg[256];  /* Modbus holding-register image (HR_*) */
} inv_runtime_t;

static inv_runtime_t g_rt;
static volatile uint32_t g_ticks;

void SysTick_Handler(void) { g_ticks++; }

/* ---- Modbus register map backed by the runtime image ---- */
static mb_exception_t mb_rd_input(void *c, uint16_t a, uint16_t *o) {
    (void)c;
    if (a >= 160) return MB_EXC_ILLEGAL_ADDRESS;
    *o = g_rt.input_reg[a];
    return MB_OK;
}
static mb_exception_t mb_rd_hold(void *c, uint16_t a, uint16_t *o) {
    (void)c;
    if (a >= 256) return MB_EXC_ILLEGAL_ADDRESS;
    *o = g_rt.holding_reg[a];
    return MB_OK;
}
static mb_exception_t mb_wr_hold(void *c, uint16_t a, uint16_t v) {
    (void)c;
    if (a >= 256) return MB_EXC_ILLEGAL_ADDRESS;
    g_rt.holding_reg[a] = v;    /* TODO: validate ranges; persist to EEPROM */
    return MB_OK;
}

static mb_config_t g_mb = {
    .address  = 1,              /* TODO: load from HR_COM_ADDR / settings */
    .check_sn = false,
    .sn       = { '0','0','0','0','0','0','0','0','0','0' },
    .regs     = { mb_rd_input, mb_rd_hold, mb_wr_hold, 0 }
};

/* ---- HMI wiring over the same register model ---- */
static bool hmi_read(hmi_regspace_t sp, uint16_t r, uint16_t *o) {
    if (sp == HMI_REG_INPUT   && r < 160) { *o = g_rt.input_reg[r];   return true; }
    if (sp == HMI_REG_HOLDING && r < 256) { *o = g_rt.holding_reg[r]; return true; }
    return false;
}
static bool hmi_write(uint16_t r, uint16_t v) {
    if (r < 256) { g_rt.holding_reg[r] = v; return true; }  /* TODO: validate + persist */
    return false;
}
static const hmi_io_t g_hmi_io = {
    hmi_read, hmi_write, hmi_lcd_draw_row, hmi_lcd_clear, 4
};
static hmi_t g_hmi;

static void systick_init_1ms(void) {
    SysTick->LOAD = (SystemCoreClock / 1000U) - 1U;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE | SysTick_CTRL_TICKINT | SysTick_CTRL_ENABLE;
}

int main(void) {
    /* seed a plausible snapshot so a Modbus poll returns real-looking data */
    g_rt.input_reg[IR_STATE] = (uint16_t)STATE_STANDBY;
    g_rt.input_reg[IR_VBAT]  = 520;          /* 52.0 V (0.1 V units) */
    g_rt.holding_reg[HR_COM_ADDR] = g_mb.address;
    (void)MENU__COUNT;                       /* HMI model available */

    systick_init_1ms();
    mb_port_init(&g_mb);

    hmi_lcd_init();
    hmi_keypad_init();
    hmi_init(&g_hmi, &hmi_root_menu, &g_hmi_io);
    hmi_render(&g_hmi);

    uint32_t last_render = 0;
    for (;;) {
        mb_port_poll(g_ticks);

        int key = hmi_keypad_poll();
        if (key >= 0) { hmi_key(&g_hmi, (hmi_key_t)key); hmi_render(&g_hmi); }
        else if ((uint32_t)(g_ticks - last_render) >= 250) {  /* refresh live values */
            last_render = g_ticks;
            hmi_render(&g_hmi);
        }
        /* TODO: fault/state machine, DSP link, settings persistence */
    }
}
