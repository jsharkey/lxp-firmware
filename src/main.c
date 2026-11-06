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
#include "inv/lcd_tft.h"
#include "inv/dsp_link.h"
#include "inv/variant.h"
#include "inv/gpio_sample.h"
#include "inv/relay.h"
#include "inv/bms_can.h"
#include "inv/bms_can_map.h"
#include "inv/safety_cpu.h"
#include "inv/config_flash.h"
#include "inv/acfirst.h"
#include "inv/rtc.h"
#include "inv/energy.h"

/* Holding registers that persist to the SPI config flash (docs/23 field map).
 * The wire value is scaled to the on-flash units the factory uses so a record
 * written here is read correctly by the factory firmware and vice-versa. */
static void settings_persist_hr(uint16_t reg, uint16_t val)
{
    switch (reg) {
    case HR_CHARGE_CURR:  config_set_u16(CFG_SLOT_MAIN, CFG_OFF_CHARGE_CURR, val * 10u); break;
    case HR_DISCHG_CURR:  config_set_u16(CFG_SLOT_MAIN, CFG_OFF_DISCHG_CURR, val * 10u); break;
    default: break;   /* not persisted (yet) */
    }
}

/* Seed the holding-register image from the config flash at boot (inverse scale). */
static void settings_seed_hr(uint16_t *hold)
{
    hold[HR_CHARGE_CURR] = config_get_u16(CFG_SLOT_MAIN, CFG_OFF_CHARGE_CURR) / 10u;
    hold[HR_DISCHG_CURR] = config_get_u16(CFG_SLOT_MAIN, CFG_OFF_DISCHG_CURR) / 10u;
}

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
    /* Publish decoded pack state into the shared register image, rescaling each
     * CAN field to its Modbus register (docs/04 / the EG4 18kPV-12LV map). The
     * factory image maps the same CAN fields to these same input registers. */
    if (g_bms.soc_soh_valid)
        g_rt.input_reg[IR_SOC_SOH] = (uint16_t)((g_bms.soh << 8) | g_bms.soc);
    if (g_bms.measured_valid) {
        /* 0x356: pack voltage 0.01 V -> IR_VBAT 0.1 V (round to nearest, matching
         * the factory); current 0.01 A and temperature 0.1 degC map 1:1 (both
         * signed) into the BMS registers. */
        g_rt.input_reg[IR_VBAT]           = (uint16_t)((g_bms.voltage_cv + 5) / 10);
        g_rt.input_reg[IR_BMS_CURRENT]    = (uint16_t)g_bms.current_ca;
        g_rt.input_reg[IR_BMS_MAX_CELL_T] = (uint16_t)g_bms.temp_dc;
    }
    if (g_bms.limits_valid)               /* 0x351 charge voltage limit 0.1 V, 1:1 */
        /* The factory additionally clamps this to a cell-count-derived max
         * (~57.4 V on this pack); we report the pack's limit as-is. */
        g_rt.input_reg[IR_BMS_CHG_VOLT_REF] = g_bms.charge_volt_dv;
    if (g_bms.alarms_valid) {             /* 0x359 protection/alarm bitfields, 1:1 */
        g_rt.input_reg[IR_BMS_FAULTCODE]    = g_bms.fault_bits;
        g_rt.input_reg[IR_BMS_WARNCODE]     = g_bms.warn_bits;
        g_rt.input_reg[IR_BMS_PARALLEL_NUM] = g_bms.module_count;  /* 0x359 [4] module count */
    }
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
    switch (a) {
    /* The time registers read back the LIVE wall clock (docs/36), not the raw
     * set value -- matching the factory, whose HR 12-14 getter reconstructs from
     * its calendar. So a dongle polling the time sees it advance. */
    case HR_TIME_YEAR_MONTH: *o = (uint16_t)(g_rtc.year   | (g_rtc.month << 8)); break;
    case HR_TIME_DATE_HOUR:  *o = (uint16_t)(g_rtc.day    | (g_rtc.hour  << 8)); break;
    case HR_TIME_MIN_SEC:    *o = (uint16_t)(g_rtc.minute | (g_rtc.sec   << 8)); break;
    default:                 *o = g_rt.holding_reg[a]; break;
    }
    return MB_OK;
}
/* A write to any Modbus time register (HR 12-14) sets the ARM wall clock. */
static void apply_if_time_reg(uint16_t reg) {
    if (reg >= HR_TIME_YEAR_MONTH && reg <= HR_TIME_MIN_SEC)
        rtc_set_from_modbus(g_rt.holding_reg[HR_TIME_YEAR_MONTH],
                            g_rt.holding_reg[HR_TIME_DATE_HOUR],
                            g_rt.holding_reg[HR_TIME_MIN_SEC]);
}

static mb_exception_t mb_wr_hold(void *c, uint16_t a, uint16_t v) {
    (void)c;
    if (a >= 256) return MB_EXC_ILLEGAL_ADDRESS;
    g_rt.holding_reg[a] = v;    /* TODO: validate ranges */
    settings_persist_hr(a, v);  /* journal persisted settings to the config flash */
    apply_if_time_reg(a);       /* HR 12-14 -> set the wall clock */
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
    if (r < 256) {
        g_rt.holding_reg[r] = v;       /* TODO: validate */
        settings_persist_hr(r, v);     /* journal persisted settings to the config flash */
        apply_if_time_reg(r);          /* HR 12-14 -> set the wall clock */
        return true;
    }
    return false;
}
/* Register access only; no display backend yet. The front-panel display is the
 * graphic LCD (lcd_tft) — the menu's on-screen rendering is future work there, so
 * draw_row/clear are NULL (hmi_render is a safe no-op) while the keypad still
 * drives the recovered navigation state machine. */
static const hmi_io_t g_hmi_io = {
    hmi_read, hmi_write, NULL, NULL, 0
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

    config_flash_init();                     /* SPI NOR up; load persisted settings */
    settings_seed_hr(g_rt.holding_reg);      /* persisted values override the defaults */

    systick_init_1ms();
    mb_port_init(&g_mb);
    bms_can_init(&g_bms);
    can_port_init();                    /* battery BMS bus on CAN1 (docs/20) */
    relay_init();
    relay_set_override(0, 0);           /* relays idle until a mode/override drives them */
    relay_set_mode(STATE_STANDBY);      /* run-enable relay follows the operating mode */

    hmi_keypad_init();
    hmi_init(&g_hmi, &hmi_root_menu, &g_hmi_io);

    /* Bring up the real graphic LCD (docs/28) and post a "hello world" — proof
     * our firmware drives the same panel as the factory image, in the same wire
     * format (the HMI simulator renders this identically). This is the front
     * panel's only display; there is no character LCD on this hardware. Done
     * after the comms GPIO is configured so it doesn't reorder their bring-up. */
    lcd_tft_init();
    lcd_text(LCD_PANEL_X0, 24, "Hello World!");

    for (int i = 0; i < MB_SN_LEN; i++) g_dsp_src.sn[i] = g_mb.sn[i];
    dsp_push_init(&g_dsp);

    uint32_t last_dsp = 0, last_bms = 0, last_rtc = 0;
    for (;;) {
        if ((uint32_t)(g_ticks - last_rtc) >= 1000) {   /* 1 Hz wall-clock tick */
            last_rtc = g_ticks;
            rtc_tick();
            /* Accumulate the energy counters (IR 28-37 / 40-59): integrate the
             * instantaneous power telemetry, gated on a running operating state;
             * then reset the daily counters if the RTC rolled to a new day. The
             * cumulative counters persist across midnight (docs/37). */
            static const uint8_t ch_pwr[ENERGY_NCH] = {
                IR_PPV1, IR_PPV2, IR_PPV3, IR_PINV, IR_PREC,
                IR_PCHARGE, IR_PDISCHARGE, IR_PEPS, IR_PTOGRID, IR_PTOUSER,
            };
            for (uint8_t ch = 0; ch < ENERGY_NCH; ch++)
                energy_set_power(ch, g_rt.input_reg[ch_pwr[ch]]);
            energy_tick((uint8_t)g_rt.input_reg[IR_STATE]);
            energy_rollover(g_rtc.day);
        }
        /* Publish the safety CPU's decoded USART2 telemetry (grid/PV/bus V,
         * frequency, temps, inverter current) into the register image before
         * serving Modbus, so the dongle sees the latest values (docs/30/33). */
        safety_cpu_publish(g_rt.input_reg, 160);
        energy_publish(g_rt.input_reg);   /* expose energy counters to IR 28-37 / 40-59 */

        mb_port_poll(g_ticks);

        can_port_poll(on_can_frame);  /* drain battery BMS telemetry -> register image */
        if ((uint32_t)(g_ticks - last_bms) >= 1000) {   /* ~1 Hz keep-alive/request to the pack */
            last_bms = g_ticks;
            static const uint8_t keepalive[8] = {0};    /* payload provisional (docs/20) */
            can_port_send(BMS_CAN_ID_INV_ALIVE, keepalive, sizeof keepalive);
        }

        pb7_sample_poll();      /* debounced PB7 line (mirrors factory sub_0802e452) */
        relay_poll();           /* apply AC transfer-relay state (PA12/PB3) */

        /* AC-First load-priority windows vs. the wall clock (docs/25, docs/36).
         * The ARM owns the clock (g_rtc): HR 12-14 writes set it and rtc_tick()
         * advances it, so this tracks real time of day. Publish "any AC-First
         * window active now" as IR 126 bit 8 -- the externally observable verdict. */
        {
            uint16_t now_min = rtc_now_minutes();
            if (acfirst_window_active(&g_rt.holding_reg[HR_ACFIRST_START_0],
                                      ACFIRST_NUM_WINDOWS, now_min))
                g_rt.input_reg[IR_ACFIRST_STATUS] |= IR_ACFIRST_WIN_ACTIVE;
            else
                g_rt.input_reg[IR_ACFIRST_STATUS] &= (uint16_t)~IR_ACFIRST_WIN_ACTIVE;
        }

        /* Front-panel keys drive the recovered menu navigation. Rendering the
         * menu on the graphic LCD (lcd_tft) is future work; until then hmi_render
         * has no display backend (g_hmi_io), so we just advance the state. */
        int key = hmi_keypad_poll();
        if (key >= 0) hmi_key(&g_hmi, (hmi_key_t)key);

        /* Push the next DSP config block (~one per 20 ms => full 8-block
         * snapshot ~6x/s). TODO: fill g_dsp_src timestamp from the RTC. */
        if ((uint32_t)(g_ticks - last_dsp) >= 20) {
            last_dsp = g_ticks;
            uint8_t frame[DSP_FRAME_MAX];
            size_t n = dsp_push_next(&g_dsp, &g_dsp_src, frame, sizeof frame);
            if (n) dsp_link_tx(frame, n);
        }
        config_flash_poll();    /* journal any changed settings to the SPI config flash */
        /* TODO: fault/state machine */
    }
}
