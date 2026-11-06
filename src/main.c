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
#include "inv/settings_map.h"
#include "inv/classify.h"
#include "inv/acfirst.h"
#include "inv/rtc.h"
#include "inv/energy.h"
#include "inv/telemetry.h"
#include "inv/settings_validate.h"
#include "inv/dsp_rx.h"

/* Holding registers that persist to the SPI config flash (docs/23 field map,
 * table in include/inv/settings_map.h). The wire value is scaled to the on-flash
 * units the factory uses, and written at the factory's slot/offset/width, so a
 * record written here is read correctly by the factory firmware and vice-versa
 * (proven both ways by tests/test_persist_crossimage.py). */
static void settings_persist_hr(uint16_t reg, uint16_t val)
{
    for (unsigned i = 0; i < SETTINGS_MAP_LEN; i++) {
        const settings_field_t *f = &SETTINGS_MAP[i];
        if (f->reg != reg) continue;
        uint16_t stored = (uint16_t)(val * f->scale);
        if (f->width == 1)
            config_set_u8(f->slot, f->off, (uint8_t)stored);
        else
            config_set_u16(f->slot, f->off, stored);
        return;
    }
    /* reg not in the pinned set -> not persisted */
}

/* Seed the holding-register image from the config flash at boot (inverse scale). */
static void settings_seed_hr(uint16_t *hold)
{
    for (unsigned i = 0; i < SETTINGS_MAP_LEN; i++) {
        const settings_field_t *f = &SETTINGS_MAP[i];
        uint16_t stored = (f->width == 1) ? config_get_u8(f->slot, f->off)
                                          : config_get_u16(f->slot, f->off);
        hold[f->reg] = (uint16_t)(stored / f->scale);
    }
}

/* Operating-state inputs the classifier turns into IR 0 / 60-63 (docs/22, T06).
 * The received DSP mode byte and the safety-CPU-relayed fault/warn words arrive
 * over USART2; that receive path is still being built (T05), so these default to
 * a clean Standby and the classifier publishes accordingly. Wiring the register
 * image THROUGH inv_classify (rather than hard-seeding Standby) means that once
 * the USART2 ingest lands, the real mode/fault/warn flow straight out to Modbus. */
typedef struct {
    uint8_t  mode_byte;      /* received operating-mode byte (DSP, via USART2)  */
    uint32_t relayed_fault;  /* safety-CPU FaultCode word (USART2)              */
    uint32_t relayed_warn;   /* safety-CPU WarningCode word (USART2)            */
    uint32_t local_flags;    /* INV_LOCAL_* overlay the ARM sets itself         */
} state_inputs_t;

static state_inputs_t g_state_in;   /* zero = Standby, no faults (clean boot)   */

/* Classify the current inputs and publish IR 0 (State) + IR 60-63 (Fault/Warn
 * 32-bit, low word then high word). Pure classifier is inv_classify(). */
static void state_publish(uint16_t *ir)
{
    inv_class_t c = inv_classify(g_state_in.mode_byte, g_state_in.relayed_fault,
                                 g_state_in.relayed_warn, g_state_in.local_flags);
    ir[IR_STATE]       = c.state;
    ir[IR_FAULTCODE_L] = (uint16_t)(c.fault & 0xFFFF);
    ir[IR_FAULTCODE_H] = (uint16_t)(c.fault >> 16);
    ir[IR_WARNCODE_L]  = (uint16_t)(c.warn & 0xFFFF);
    ir[IR_WARNCODE_H]  = (uint16_t)(c.warn >> 16);
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
    sv_result_t sv = settings_validate(a, v);   /* range / read-only check (T04) */
    if (sv.exc != MB_OK) return sv.exc;          /* reject out-of-range / read-only */
    g_rt.holding_reg[a] = sv.value;
    settings_persist_hr(a, sv.value);  /* journal persisted settings to the config flash */
    apply_if_time_reg(a);              /* HR 12-14 -> set the wall clock */
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
        sv_result_t sv = settings_validate(r, v);   /* same validation as the dongle (T04) */
        if (sv.exc != MB_OK) return false;           /* reject out-of-range / read-only */
        g_rt.holding_reg[r] = sv.value;
        settings_persist_hr(r, sv.value);  /* journal persisted settings to the config flash */
        apply_if_time_reg(r);              /* HR 12-14 -> set the wall clock */
        return true;
    }
    return false;
}
/* Register access + the display backend: the menu renders on the graphic LCD
 * (src/hmi/hmi_tft.c -> src/hmi/lcd_tft.c), the front panel's only display. */
static const hmi_io_t g_hmi_io = {
    hmi_read, hmi_write, hmi_tft_draw_row, hmi_tft_clear, HMI_TFT_ROWS
};
static hmi_t g_hmi;

/* ---- ARM -> DSP config push (docs/08): continuous full snapshot ---- */
static bool dsp_rd_holding(void *c, uint16_t reg, uint16_t *o) {
    (void)c;
    if (reg >= 256) return false;
    *o = g_rt.holding_reg[reg];
    return true;
}
/* ARM-computed telemetry (T07). The internal quantities are fed from the DSP /
 * safety-CPU links once those RX paths land (T05/T09); inv_telemetry_publish()
 * serves them to the dongle input registers with the factory scaling. */
inv_telemetry_t g_telemetry;

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
    state_publish(g_rt.input_reg);           /* IR 0 / 60-63 via the classifier */
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
    mb_port_init(&g_mb);                 /* dongle Modbus slave on UART5 (docs/26) */
    dsp_link_port_init(19200U);          /* USART3 is the DSP link's alone now */
    bms_can_init(&g_bms);
    can_port_init();                    /* battery BMS bus on CAN1 (docs/20) */
    relay_init();
    relay_set_override(0, 0);           /* relays idle until a mode/override drives them */
    relay_set_mode(STATE_STANDBY);      /* run-enable relay follows the operating mode */

    /* Bring up the real graphic LCD (docs/28) — the front panel's only display,
     * same panel and wire format as the factory image (the HMI simulator renders
     * it identically) — then paint the menu. Done after the comms GPIO is
     * configured so the LCD bit-bang doesn't reorder their bring-up. */
    hmi_keypad_init();
    lcd_tft_init();
    hmi_init(&g_hmi, &hmi_root_menu, &g_hmi_io);
    /* The initial menu is painted once from inside the loop (below), not here: a
     * full-panel bit-bang repaint is millions of instructions, and doing it in
     * init would delay the loop reaching mb_port_poll past the comms boot
     * budget. */

    for (int i = 0; i < MB_SN_LEN; i++) g_dsp_src.sn[i] = g_mb.sn[i];
    dsp_push_init(&g_dsp);

    uint32_t last_dsp = 0, last_bms = 0, last_rtc = 0;
    bool hmi_painting = true;           /* paint the initial menu, one row per pass */
    uint8_t paint_row = 0;
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
            inv_telemetry_runtime_tick(&g_telemetry, (uint8_t)g_rt.input_reg[IR_STATE]);
        }
        /* Publish the safety CPU's decoded USART2 telemetry (grid/PV/bus V,
         * frequency, temps, inverter current) into the register image before
         * serving Modbus, so the dongle sees the latest values (docs/30/33). */
        safety_cpu_publish(g_rt.input_reg, 160);
        inv_telemetry_publish(g_rt.input_reg, &g_telemetry);  /* ARM-computed powers / Seps / runtime (T07) */
        state_publish(g_rt.input_reg);    /* IR 0 State + IR 60-63 Fault/Warn (docs/22, T06a) */
        energy_publish(g_rt.input_reg);   /* expose energy counters to IR 28-37 / 40-59 */

        mb_port_poll(g_ticks);

        /* Service the ARM<->DSP link's receive side on USART3: the DSP polls the
         * ARM as a Modbus slave here (func 03/04/06/10) and sends firmware-update
         * frames (21/22/23); a 0x49 telemetry SOF is rejected -- the ARM does not
         * consume DSP telemetry on this wire (docs/wiring/ARM-USART3-DSP, T09). */
        inv_dsp_rx_poll(&g_mb, g_ticks);

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

        /* Front-panel keys drive the menu. A key (or the first pass) marks the
         * screen dirty; the repaint is then spread ONE ROW per loop iteration
         * (below) instead of all at once. A full-panel bit-bang repaint is
         * millions of instructions — doing it in a single pass would stall the
         * cooperative loop (Modbus, CAN, DSP push) for that whole time. Painting
         * a row at a time keeps each pass cheap so comms stays serviced. */
        int key = hmi_keypad_poll();
        if (key >= 0) {
            hmi_key(&g_hmi, (hmi_key_t)key);
            paint_row = 0; hmi_painting = true;   /* restart the incremental repaint */
        }
        if (hmi_painting) {
            hmi_render_row(&g_hmi, paint_row);
            if (++paint_row >= HMI_TFT_ROWS) hmi_painting = false;
        }

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
