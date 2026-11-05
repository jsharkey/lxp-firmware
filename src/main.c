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
#include "inv/dsp_link.h"
#include "inv/variant.h"
#include "inv/gpio_sample.h"
#include "inv/relay.h"
#include "inv/bms_can.h"
#include "inv/bms_can_map.h"

/* Shared system snapshot the subsystems read/write. */
typedef struct {
    uint16_t input_reg[160];    /* Modbus input-register image (IR_*)   */
    uint16_t holding_reg[256];  /* Modbus holding-register image (HR_*) */
} inv_runtime_t;

static inv_runtime_t g_rt;
static volatile uint32_t g_ticks;

void SysTick_Handler(void) { g_ticks++; }

/* ---- battery BMS over CAN1 -> the Modbus input-register image ---- */
static bms_pack_t g_bms;

static void on_can_frame(uint32_t id, const uint8_t *data, uint8_t dlc) {
    if (!bms_can_on_frame(&g_bms, id, data, dlc)) return;
    /* Publish decoded pack state into the shared register image. IR_SOC_SOH
     * packs SOC in the low byte and SOH in the high byte (docs/04). */
    if (g_bms.soc_soh_valid)
        g_rt.input_reg[IR_SOC_SOH] = (uint16_t)((g_bms.soh << 8) | g_bms.soc);
}

/* ---- Modbus register map backed by the runtime image ---- */
static mb_exception_t mb_rd_input(void *c, uint16_t a, uint16_t *o) {
    (void)c;
    if (a >= 160) return MB_EXC_ILLEGAL_ADDRESS;
    /* Variant gating: the Modbus map is the 18kPV superset. On a 2-MPPT build
     * the 3rd-tracker slots are not meaningful, so report a well-formed 0
     * instead of whatever happens to be in the image. */
    *o = inv_ir_active(a) ? g_rt.input_reg[a] : 0;
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

/* ---- ARM -> DSP config push (docs/08): continuous full snapshot ---- */
static bool dsp_rd_holding(void *c, uint16_t reg, uint16_t *o) {
    (void)c;
    if (reg >= 256) return false;
    *o = g_rt.holding_reg[reg];
    return true;
}
static dsp_push_t  g_dsp;
static dsp_cfg_src_t g_dsp_src = { .address = 0, .read_holding = dsp_rd_holding };

static void systick_init_1ms(void) {
    SysTick->LOAD = (SystemCoreClock / 1000U) - 1U;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE | SysTick_CTRL_TICKINT | SysTick_CTRL_ENABLE;
}

int main(void) {
    const inv_variant_t *v = inv_variant();  /* the model this build targets */

    /* seed a plausible snapshot so a Modbus poll returns real-looking data */
    g_rt.input_reg[IR_STATE] = (uint16_t)STATE_STANDBY;
    g_rt.input_reg[IR_VBAT]  = 520;          /* 52.0 V (0.1 V units) */
    g_rt.input_reg[IR_VPV1]  = 3200;         /* 320.0 V */
    g_rt.input_reg[IR_VPV2]  = 3180;         /* 318.0 V */
    if (inv_has_mppt3())                     /* 3rd tracker only on 18kPV */
        g_rt.input_reg[IR_VPV3] = 3150;      /* 315.0 V */
    g_rt.holding_reg[HR_COM_ADDR] = g_mb.address;
    (void)MENU__COUNT;                       /* HMI model available */
    (void)v;                                 /* name/model_code used by HMI/DSP */

    systick_init_1ms();
    mb_port_init(&g_mb);
    bms_can_init(&g_bms);
    can_port_init();                    /* battery BMS bus on CAN1 (docs/20) */
    relay_init();
    relay_set_override(0, 0);           /* relays idle until a mode/override drives them */
    relay_set_mode(STATE_STANDBY);      /* run-enable relay follows the operating mode */

    hmi_lcd_init();
    hmi_keypad_init();
    hmi_init(&g_hmi, &hmi_root_menu, &g_hmi_io);
    hmi_render(&g_hmi);

    for (int i = 0; i < MB_SN_LEN; i++) g_dsp_src.sn[i] = g_mb.sn[i];
    dsp_push_init(&g_dsp);

    uint32_t last_render = 0, last_dsp = 0, last_bms = 0;
    for (;;) {
        mb_port_poll(g_ticks);

        can_port_poll(on_can_frame);  /* drain battery BMS telemetry -> register image */
        if ((uint32_t)(g_ticks - last_bms) >= 1000) {   /* ~1 Hz keep-alive/request to the pack */
            last_bms = g_ticks;
            static const uint8_t keepalive[8] = {0};    /* payload provisional (docs/20) */
            can_port_send(BMS_CAN_ID_INV_ALIVE, keepalive, sizeof keepalive);
        }

        pb7_sample_poll();      /* debounced PB7 line (mirrors factory sub_0802e452) */
        relay_poll();           /* apply AC transfer-relay state (PA12/PB3) */

        int key = hmi_keypad_poll();
        if (key >= 0) { hmi_key(&g_hmi, (hmi_key_t)key); hmi_render(&g_hmi); }
        else if ((uint32_t)(g_ticks - last_render) >= 250) {  /* refresh live values */
            last_render = g_ticks;
            hmi_render(&g_hmi);
        }

        /* Push the next DSP config block (~one per 20 ms => full 8-block
         * snapshot ~6x/s). TODO: fill g_dsp_src timestamp from the RTC. */
        if ((uint32_t)(g_ticks - last_dsp) >= 20) {
            last_dsp = g_ticks;
            uint8_t frame[DSP_FRAME_MAX];
            size_t n = dsp_push_next(&g_dsp, &g_dsp_src, frame, sizeof frame);
            if (n) dsp_link_tx(frame, n);
        }
        /* TODO: fault/state machine, settings persistence */
    }
}
