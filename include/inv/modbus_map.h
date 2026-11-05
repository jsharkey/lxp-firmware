/*
 * Modbus-RTU register map — AUTHORITATIVE (external interface contract).
 *
 * Source: EG4 18kPV-12LV Modbus RTU Protocol (public document).
 * The ARM "com" MCU implements this as a Modbus-RTU *slave*. Reproducing this
 * map exactly is a hard requirement for monitoring-tool compatibility.
 *
 * Per-register prose — what each register means, where its data comes from
 * (for inputs) and the side-effects of writing it (for holdings) — lives in
 * docs/modbus-dongle/ (authoritative for the dongle surface). This header is
 * the machine-readable companion to that tree.
 *
 * TARGET DEVICE NOTE: this map is the 18kPV-12LV SUPERSET. The firmware builds
 * for two variants (see include/inv/variant.h): the EG4 18kPV (hybrid, 3 MPPT)
 * uses it in full; the EG4 12000XP (non-hybrid, 2 MPPT) leaves some entries
 * UNUSED:
 *   - IR_VPV3 / IR_PPV3 / IR_EPV3_DAY / IR_EPV3_ALL_* (no 3rd MPPT)
 *   - hybrid grid-tie-only items (e.g. AC-couple) may read 0 / be inactive.
 * Gate per-model at runtime with inv_ir_active() / inv_is_hybrid() rather than
 * assuming a single target. See docs/10-18kpv-vs-12000xp.md.
 *
 * Link settings:
 *   RS-485, UART, 19200 bps, 8 data bits, no parity, 1 stop bit (8N1).
 *   Minimum polling period: 1 s.  Register width: 2 bytes.
 *   Function codes: 0x03 read holding, 0x04 read input,
 *                   0x06 write single holding, 0x10 write multiple holding
 *                   (0x10 only valid for serial number and time setting).
 *
 * Wire encoding quirks (IMPORTANT):
 *   - 16-bit value byte order is REVERSED: bytes 0x01 0x02 -> value 0x0201.
 *   - 32-bit value = two regs; word order reversed AND bytes within each word
 *     reversed: 0x01 0x02 0x03 0x04 -> 0x04030201.
 *   - Every request/response frame carries a 10-byte serial number SN[0..9]
 *     (ASCII) immediately after the function code (see holding regs 2-6).
 *   - A single query may span at most 40 registers, and must not cross a
 *     40-register group boundary (groups: 0-39, 40-79, 80-119, ...).
 *
 * Scaling is given per entry as a comment: multiply the raw register by the
 * factor to get the engineering value (e.g. 0.1V -> volts = raw * 0.1).
 * "s16"/"s32" mark signed quantities. "L/H" pairs form one 32-bit value.
 */
#ifndef INV_MODBUS_MAP_H
#define INV_MODBUS_MAP_H

#define MB_BAUD              19200
#define MB_FORMAT_8N1        1
#define MB_REG_WIDTH_BYTES   2
#define MB_SN_LEN            10
#define MB_MAX_REGS_PER_QUERY 40
#define MB_FC_READ_HOLDING   0x03
#define MB_FC_READ_INPUT     0x04
#define MB_FC_WRITE_SINGLE   0x06
#define MB_FC_WRITE_MULTI    0x10

/* ============================ INPUT REGISTERS (0x04, read-only) =========== */
enum mb_input_reg {
    IR_STATE            = 0,   /* operating mode bitmask, see inv/states.h       */
    IR_VPV1             = 1,   /* 0.1 V   PV1 voltage                            */
    IR_VPV2             = 2,   /* 0.1 V   PV2 voltage                            */
    IR_VPV3             = 3,   /* 0.1 V   PV3 voltage                            */
    IR_VBAT             = 4,   /* 0.1 V   battery voltage                        */
    IR_SOC_SOH          = 5,   /* low byte SOC %, high byte SOH %                */
    IR_INTERNAL_FAULT   = 6,   /* internal DTC                                   */
    IR_PPV1             = 7,   /* 1 W     PV1 power                              */
    IR_PPV2             = 8,   /* 1 W     PV2 power                              */
    IR_PPV3             = 9,   /* 1 W     PV3 power                              */
    IR_PCHARGE          = 10,  /* 1 W     battery charge power                   */
    IR_PDISCHARGE       = 11,  /* 1 W     battery discharge power                */
    IR_VAC_R            = 12,  /* 0.1 V   grid voltage R (L1)                    */
    IR_VAC_S            = 13,  /* 0.1 V   grid voltage S (L2)                    */
    IR_VAC_T            = 14,  /* 0.1 V   grid voltage T                         */
    IR_FAC              = 15,  /* 0.01 Hz grid frequency                         */
    IR_PINV             = 16,  /* 1 W     inverter output power (grid port)      */
    IR_PREC             = 17,  /* 1 W     AC charging rectified power            */
    IR_IINV_RMS         = 18,  /* 0.01 A  inverter current RMS                   */
    IR_PF               = 19,  /* 0.001   power factor (see doc note on range)   */
    IR_VEPS_R           = 20,  /* 0.1 V   EPS output voltage R (L1)              */
    IR_VEPS_S           = 21,  /* 0.1 V   EPS output voltage S (L2)              */
    IR_VEPS_T           = 22,  /* 0.1 V   EPS output voltage T                   */
    IR_FEPS             = 23,  /* 0.01 Hz EPS output frequency                   */
    IR_PEPS             = 24,  /* 1 W     EPS active power                        */
    IR_SEPS             = 25,  /* 1 VA    EPS apparent power                      */
    IR_PTOGRID          = 26,  /* 1 W     export power to grid                    */
    IR_PTOUSER          = 27,  /* 1 W     import power from grid                  */
    IR_EPV1_DAY         = 28,  /* 0.1 kWh PV1 generation today                   */
    IR_EPV2_DAY         = 29,  /* 0.1 kWh PV2 generation today                   */
    IR_EPV3_DAY         = 30,  /* 0.1 kWh PV3 generation today                   */
    IR_EINV_DAY         = 31,  /* 0.1 kWh grid-tied inverter output today        */
    IR_EREC_DAY         = 32,  /* 0.1 kWh AC charge rectified today              */
    IR_ECHG_DAY         = 33,  /* 0.1 kWh charged today                          */
    IR_EDISCHG_DAY      = 34,  /* 0.1 kWh discharged today                       */
    IR_EEPS_DAY         = 35,  /* 0.1 kWh EPS output today                       */
    IR_ETOGRID_DAY      = 36,  /* 0.1 kWh export to grid today                   */
    IR_ETOUSER_DAY      = 37,  /* 0.1 kWh import from grid today                 */
    IR_VBUS1            = 38,  /* 0.1 V   bus 1 voltage                          */
    IR_VBUS2            = 39,  /* 0.1 V   bus 2 voltage                          */
    /* 40..59 : cumulative energy counters, each a 32-bit L/H pair, 0.1 kWh */
    IR_EPV1_ALL_L=40, IR_EPV1_ALL_H=41, IR_EPV2_ALL_L=42, IR_EPV2_ALL_H=43,
    IR_EPV3_ALL_L=44, IR_EPV3_ALL_H=45, IR_EINV_ALL_L=46, IR_EINV_ALL_H=47,
    IR_EREC_ALL_L=48, IR_EREC_ALL_H=49, IR_ECHG_ALL_L=50, IR_ECHG_ALL_H=51,
    IR_EDISCHG_ALL_L=52, IR_EDISCHG_ALL_H=53, IR_EEPS_ALL_L=54, IR_EEPS_ALL_H=55,
    IR_ETOGRID_ALL_L=56, IR_ETOGRID_ALL_H=57, IR_ETOUSER_ALL_L=58, IR_ETOUSER_ALL_H=59,
    IR_FAULTCODE_L      = 60,  /* 32-bit fault bitfield, see inv/faults.h        */
    IR_FAULTCODE_H      = 61,
    IR_WARNCODE_L       = 62,  /* 32-bit warning bitfield, see inv/faults.h      */
    IR_WARNCODE_H       = 63,
    IR_T_INNER          = 64,  /* 1 C (s16) internal ring temperature            */
    IR_T_RADIATOR1      = 65,  /* 1 C (s16) radiator temperature 1               */
    IR_T_RADIATOR2      = 66,  /* 1 C (s16) radiator temperature 2               */
    IR_T_BAT            = 67,  /* 1 C (s16) battery temperature                  */
    IR_RUNTIME_L        = 69,  /* 1 s     runtime (32-bit L/H)                   */
    IR_RUNTIME_H        = 70,
    IR_AUTOTEST         = 71,  /* packed: start/status/step nibbles              */
    IR_AUTOTEST_LIMIT   = 72,  /* 0.1 V / 0.01 Hz depending on step              */
    IR_AUTOTEST_DEFT_MS = 73,  /* ms                                             */
    IR_AUTOTEST_TRIPVAL = 74,  /* 0.1 V / 0.01 Hz depending on step              */
    IR_AUTOTEST_TRIP_MS = 75,  /* ms                                             */
    IR_AC_INPUT_TYPE    = 77,  /* 0 grid, 1 generator (12K hybrid)               */
    /* 81..112 : BMS block */
    IR_BMS_MAX_CHG_CURR = 81,  /* 0.01 A                                         */
    IR_BMS_MAX_DIS_CURR = 82,  /* 0.01 A                                         */
    IR_BMS_CHG_VOLT_REF = 83,  /* 0.1 V                                          */
    IR_BMS_DIS_CUT_VOLT = 84,  /* 0.1 V                                          */
    IR_BMS_STATUS0      = 85,  /* ... BatStatus0..9_BMS at 85..94                */
    IR_BMS_STATUS_INV   = 95,
    IR_BMS_PARALLEL_NUM = 96,
    IR_BMS_CAPACITY_AH  = 97,
    IR_BMS_CURRENT      = 98,  /* 0.01 A (s16)                                   */
    IR_BMS_FAULTCODE    = 99,
    IR_BMS_WARNCODE     = 100,
    IR_BMS_MAX_CELL_V   = 101, /* 0.001 V                                        */
    IR_BMS_MIN_CELL_V   = 102, /* 0.001 V                                        */
    IR_BMS_MAX_CELL_T   = 103, /* 0.1 C (s16)                                    */
    IR_BMS_MIN_CELL_T   = 104, /* 0.1 C (s16)                                    */
    IR_BMS_FW_UPD_STATE = 105,
    IR_BMS_CYCLE_CNT    = 106,
    IR_BAT_VOLT_INV     = 107, /* 0.1 V   inverter-side battery sample           */
    IR_T1               = 108, /* 0.1 C   12K BT temperature                     */
    IR_PARALLEL_INFO    = 113, /* bit0-1 master/slave, bit2-3 phase, bit8-16 num */
    IR_VBUS_P           = 120, /* 0.1 V   half-bus voltage                       */
    IR_GEN_VOLT         = 121, /* 0.1 V   generator voltage                      */
    IR_GEN_FREQ         = 122, /* 0.01 Hz generator frequency                    */
    IR_GEN_POWER        = 123, /* 1 W     generator power                        */
    IR_EGEN_DAY         = 124, /* 0.1 kWh generator energy today                 */
    IR_EGEN_ALL_L       = 125, /* 0.1 kWh (32-bit L/H)                           */
    IR_EGEN_ALL_H       = 126,
    IR_EPS_VOLT_L1N     = 127, /* 0.1 V                                          */
    IR_EPS_VOLT_L2N     = 128, /* 0.1 V                                          */
    IR_PEPS_L1N         = 129, /* 1 W                                            */
    IR_PEPS_L2N         = 130, /* 1 W                                            */
    IR_SEPS_L1N         = 131, /* 1 VA                                           */
    IR_SEPS_L2N         = 132, /* 1 VA                                           */
    IR_EEPS_L1N_DAY     = 133, /* 0.1 kWh                                        */
    IR_EEPS_L2N_DAY     = 134, /* 0.1 kWh                                        */
    IR_EEPS_L1N_ALL_L   = 135, IR_EEPS_L1N_ALL_H = 136,
    IR_EEPS_L2N_ALL_L   = 137, IR_EEPS_L2N_ALL_H = 138,
    IR_AFCI_CURR_CH1    = 140, /* mA ... CH1..CH4 at 140..143                    */
    IR_AFCI_FLAGS       = 144, /* arc alarm + self-test bits per channel         */
    IR_AFCI_ARC_CH1     = 145, /* real-time arc CH1..CH4 at 145..148             */
    IR_AFCI_MAXARC_CH1  = 149  /* max arc CH1..CH4 at 149..152                   */
};

/* --- Undocumented per-pack battery range (input registers 5000-5126) --------
 * Beyond the aggregate map above, the factory serves PER-PACK battery telemetry
 * on a separate high range (not in any public EG4 map). The serializer routes
 * input registers 5000-5126 to a dedicated getter (factory sub_08020cc0) backed
 * by a per-pack array filled from the CAN per-pack frames (id 0x400|sub<<5|pack,
 * parser sub_080205d4): 30 register slots per pack (bases 5000/5030/5060/5090,
 * 27 u16 fields used), paged for >4 packs. The full field map (register <->
 * CAN subtype/byte provenance) and the addressing macros live in
 * include/inv/perpack_map.h; see docs/34 (§2b) and
 * tests/test_arm_sim_factory_only.py::test_per_pack_telemetry_reaches_modbus.
 * Our firmware does not implement this range yet (a per-pack superset). */

/* ============================ HOLDING REGISTERS (0x03/0x06/0x10) ========== */
/* Settings / commands. Only the most load-bearing entries are named here;
 * the full table (incl. grid-code protection curves 25-62, the AC-charge /
 * charge-priority / forced-discharge time-window blocks 64-89, and the 48-slot
 * OptimalChg_DisChg 2-bit time table at 126-131) is in docs/04-modbus.md. */
enum mb_hold_reg {
    HR_SN_START         = 2,   /* SN[0..9] ASCII serial number, regs 2-6         */
    /* --- Firmware-version registers: one byte per processor in the system.
       The EG4 protocol names three CPUs; the standard device naming used across
       this project (docs/01, docs/16, docs/22) is:
         - Control CPU       = TI C2000 DSP (power stage / MPPT / grid sync)
         - Communication CPU = this STM32F103 com/HMI MCU  << THIS PROJECT >>
         - Redundant CPU     = the 3rd on-board "safety" MCU (docs/29)
       Traced to source in the factory ARM image (12000XP `ceaa`) via the holding
       getter `fn_ceaa` @0x08032000 — see docs/32:
         reg 9  = mov #0x0500                 -> low=0x00, high=0x05
         reg 10 = [0x20009e54+2] | (0x01<<8)  -> low=USART2 bank, high=0x01       */
    HR_SLAVE_COM_VER    = 9,   /* low  = REDUNDANT CPU ver: const 0x00 — not populated
                                          in this 12000XP image (safety CPU; docs/29)
                                  high = COMMUNICATION CPU ver: const — the ARM's own
                                          baked-in FW version (this project)          */
    HR_CNTL_FW_VER      = 10,  /* low  = CONTROL CPU (DSP) ver: from the USART2 bank
                                          byte +2 (0x20009e56, written by the USART2
                                          parser sub_080241a8) — the DSP's version
                                          RELAYED to the ARM via the safety CPU on
                                          USART2, not a direct DSP link (docs/30/31)
                                  high = FW version code: const (ARM-side build code) */
    HR_RESET_SETTING    = 11,  /* bitfield: clear records / restore defaults /…  */
    HR_TIME_YEAR_MONTH  = 12,  /* low: year(17-255), high: month(1-12)           */
    HR_TIME_DATE_HOUR   = 13,
    HR_TIME_MIN_SEC     = 14,
    HR_COM_ADDR         = 15,  /* Modbus slave address 0-150                     */
    HR_LANGUAGE         = 16,  /* 0 English, 1 German                            */
    HR_PV_INPUT_MODEL   = 20,  /* 0-7 (12K hybrid): PV routing/parallel          */
    HR_FUNC_EN          = 21,  /* bitfield: EPS/DRMS/LVRT/AntiIsland/ACCharge/…  */
    HR_START_PV_VOLT    = 22,  /* 0.1 V (900-5000) PV start voltage              */
    HR_CONNECT_TIME     = 23,  /* s (30-600) grid connect wait                   */
    HR_RECONNECT_TIME   = 24,  /* s (0-900) reconnect wait                       */
    /* 25-62: grid-code protection curves (volt/freq levels 1-3 + Q(V)/PF) */
    HR_REACTIVE_CMD_TYPE= 59,  /* 0-7 reactive command mode                      */
    HR_ACTIVE_PCT_CMD   = 60,  /* % active power limit (also 143 in 0.1%)        */
    HR_REACTIVE_PCT_CMD = 61,  /* %                                              */
    HR_PF_CMD           = 62,  /* 0.001 PF command                               */
    /* --- Battery charge/discharge schedule (regs 64-89). Each *_TIME register
       is packed hour|minute: low byte = hour (0-23), high byte = minute (0-59)
       -- same u16 = (minute<<8)|hour encoding as the AC-First windows. The DSP
       pulls these by reading holding-register group 40-79 / 80-119 over the
       link and evaluates the windows against the clock the ARM pushes (docs/08,
       docs/09). Three parallel features, each: PowerCMD, SOCLimit, 3 windows. */
    HR_CHG_POWER_PCT    = 64,  /* % (0-100) charge power percentage              */
    HR_DISCHG_POWER_PCT = 65,  /* % (0-100) discharge power percentage           */
    HR_ACCHG_POWER_PCT  = 66,  /* % (0-100) AC-charge power percentage            */
    HR_ACCHG_SOC_LIMIT  = 67,  /* % (0-100) AC-charge SOC limit                   */
    HR_ACCHG_START_0    = 68,  /* AC-charge window 0 start (hour|minute)          */
    HR_ACCHG_END_0      = 69,  /* AC-charge window 0 end                          */
    HR_ACCHG_START_1    = 70,  /* AC-charge window 1 start                        */
    HR_ACCHG_END_1      = 71,  /* AC-charge window 1 end                          */
    HR_ACCHG_START_2    = 72,  /* AC-charge window 2 start                        */
    HR_ACCHG_END_2      = 73,  /* AC-charge window 2 end                          */
    HR_CHGFIRST_POWER   = 74,  /* % (0-100) charge-priority power percentage      */
    HR_CHGFIRST_SOC     = 75,  /* % (0-100) charge-priority SOC limit             */
    HR_CHGFIRST_START_0 = 76,  /* charge-priority window 0 start (hour|minute)    */
    HR_CHGFIRST_END_0   = 77,  /* charge-priority window 0 end                    */
    HR_CHGFIRST_START_1 = 78,  /* charge-priority window 1 start                  */
    HR_CHGFIRST_END_1   = 79,  /* charge-priority window 1 end                    */
    HR_CHGFIRST_START_2 = 80,  /* charge-priority window 2 start                  */
    HR_CHGFIRST_END_2   = 81,  /* charge-priority window 2 end                    */
    HR_FDISCHG_POWER    = 82,  /* % (0-100) forced-discharge power percentage     */
    HR_FDISCHG_SOC      = 83,  /* % (0-100) forced-discharge SOC limit            */
    HR_FDISCHG_START_0  = 84,  /* forced-discharge window 0 start (hour|minute)   */
    HR_FDISCHG_END_0    = 85,  /* forced-discharge window 0 end                   */
    HR_FDISCHG_START_1  = 86,  /* forced-discharge window 1 start                 */
    HR_FDISCHG_END_1    = 87,  /* forced-discharge window 1 end                   */
    HR_FDISCHG_START_2  = 88,  /* forced-discharge window 2 start                 */
    HR_FDISCHG_END_2    = 89,  /* forced-discharge window 2 end                   */
    HR_EPS_VOLT_SET     = 90,  /* 1 V (208/230/240/277) EPS output voltage       */
    HR_EPS_FREQ_SET     = 91,  /* 1 Hz (50/60) EPS output frequency              */
    HR_CHARGE_VOLT_REF  = 99,  /* 0.1 V lead-acid charge voltage (500-590)       */
    HR_CUT_VOLT_DISCHG  = 100, /* 0.1 V lead-acid discharge cutoff (400-500)     */
    HR_CHARGE_CURR      = 101, /* A (0-140) charge current                       */
    HR_DISCHG_CURR      = 102, /* A (0-140) discharge current                    */
    HR_MAX_BACKFLOW     = 103, /* % feed-in grid power limit                     */
    HR_EOD              = 105, /* % (10-90) end-of-discharge SOC                 */
    HR_FUNCTION_EN1     = 110, /* bits: PVGridOffEn/FastZeroExport/MicroGrid/
                                  BatShared/ChgLastEn/CTSampleRatio/PVCTSampleRatio */
    HR_SET_SYSTEM_TYPE  = 112, /* 0 non-parallel, 1 1ph parallel master, 2 slave,
                                  3 3ph parallel master                          */
    HR_SET_COMPOSED_PH  = 113, /* 1 R, 2 S, 3 T (phase in parallel system)       */
    HR_SYS_ENABLE       = 120, /* bits: HalfHourACChrStart/ACChargeType/
                                  DischgCtrlType/OnGridEODType/GenChargeType      */
    HR_FLOAT_CHARGE_VOLT= 144, /* 0.1 V (500-560) lead-acid float voltage        */
    HR_OUTPUT_PRIO_CFG  = 145, /* 0 bat-first, 1 PV-first, 2 AC-first            */
    HR_LINE_MODE        = 146, /* 0 APL, 1 UPS, 2 GEN                            */
    HR_BAT_CAPACITY_AH  = 147, /* Ah (unmatched batteries)                       */
    HR_BAT_NOMINAL_VOLT = 148, /* 0.1 V (400-590)                                */
    /* AC-First load-priority time windows: three {start,end} pairs, each packed
       u16 = (minute<<8)|hour (docs/08, docs/25). Evaluated against the ARM RTC;
       the "active now" verdict surfaces at IR 126 bit 8 (IR_ACFIRST_STATUS). */
    HR_ACFIRST_START_0  = 152,
    HR_ACFIRST_END_0    = 153,
    HR_ACFIRST_START_1  = 154,
    HR_ACFIRST_END_1    = 155,
    HR_ACFIRST_START_2  = 156,
    HR_ACFIRST_END_2    = 157,
    HR_GEN_CHG_START_V  = 194, /* 0.1 V (384-520)                                */
    HR_GEN_CHG_END_V    = 195, /* 0.1 V (480-590)                                */
    HR_GEN_CHG_START_SOC= 196, /* % (0-90)                                       */
    HR_GEN_CHG_END_SOC  = 197, /* % (20-100)                                     */
    HR_MAX_GEN_CHG_CURR = 198  /* A (0-60)                                       */
};

/* AC-First "window active now" status. The factory overloads *input* register
 * 126 as a status word and reports the AC-First-window verdict in bit 8 (docs/25
 * -- note this is the input-register space, distinct from the OptimalChg_DisChg
 * *holding* registers 126-131). IR 126 is also IR_EGEN_ALL_H in the register
 * map; the status bit lives alongside that overload, matching the oracle. */
#define IR_ACFIRST_STATUS      126u
#define IR_ACFIRST_WIN_ACTIVE  (1u << 8)

#endif /* INV_MODBUS_MAP_H */
