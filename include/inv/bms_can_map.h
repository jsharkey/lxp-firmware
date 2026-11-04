/*
 * Battery BMS CAN map — the inverter's view of the "CAN1 / battery BMS bus".
 *
 * RECOVERED from the EG4 battery BMS factory image BATT_IN280-Z03T13.bin
 * (Huada HC32F460-class MCU; see docs/20-battery-bms-firmware.md). This is the
 * de-facto inverter "CAN bus battery" protocol (SMA/Victron/Pylontech family,
 * 11-bit IDs). The battery is the TX master of the 0x3xx telemetry frames; the
 * inverter transmits the 0x30x/0x400 control frames.
 *
 * STATUS: the 0x351/0x355/0x356 telemetry layouts below are byte-exact reads of
 * the battery's frame builder (FUN_0002a0bc, standard/little-endian preset path
 * — see docs/20). The alarm/flag bit positions (0x359/0x35a/0x35c) are partially
 * recovered; marked PARTIAL. The bus baud is pending an SBT decode (expect
 * 500 kbit/s).
 *
 * MULTI-PRESET WARNING: the BMS carries 8 selectable inverter-brand presets
 * (P01-EG4 … P07-LUX … P08-SMA). This map is the standard little-endian preset
 * (the one EG4/Victron/SMA expect). Other presets reorder bytes and at least one
 * preset path packs these same fields BIG-endian. Our inverter pairs with the
 * P07-LUX / P01-EG4 profile; confirm the active preset before trusting byte
 * order on a live bus.
 *
 * Wire encoding (standard preset):
 *   - 11-bit standard CAN IDs, classic (non-FD) frames.
 *   - Multi-byte fields are LITTLE-endian (byte[0] = LSB).
 *   - Scaling per field below; "s16" marks signed.
 */
#ifndef INV_BMS_CAN_MAP_H
#define INV_BMS_CAN_MAP_H

#include <stdint.h>

/* Bus parameters (baud PENDING — SBT decode; 500k is the universal default). */
#define BMS_CAN_BAUD_EXPECTED   500000u

/* ---- Battery -> inverter telemetry frames (TX master = battery) ---- */
#define BMS_CAN_ID_LIMITS       0x351u  /* charge/discharge V & I limits   */
#define BMS_CAN_ID_SOC_SOH      0x355u  /* SOC / SOH                       */
#define BMS_CAN_ID_VIT          0x356u  /* pack voltage / current / temp   */
#define BMS_CAN_ID_ALARM_A      0x359u  /* protection & alarm bitfields    */
#define BMS_CAN_ID_ALARM_B      0x35Au  /* alarms / warnings (2nd set)     */
#define BMS_CAN_ID_EXT_STATUS   0x35Bu  /* extended status                 */
#define BMS_CAN_ID_REQ_FLAGS    0x35Cu  /* charge/discharge request flags  */
#define BMS_CAN_ID_MFR_NAME     0x35Eu  /* manufacturer name ("EG4/LUX")   */
#define BMS_CAN_ID_FW_CAP       0x35Fu  /* firmware / capacity info        */
/* Extended/per-module reporting also present: 0x311-0x321, 0x370-0x381. */

/* ---- Inverter -> battery control frames (TX master = inverter) ---- */
#define BMS_CAN_ID_INV_300      0x300u  /* inverter request                */
#define BMS_CAN_ID_INV_CONFIG   0x301u  /* inverter config/handshake       */
#define BMS_CAN_ID_INV_ALIVE    0x305u  /* inverter keep-alive / heartbeat */
#define BMS_CAN_ID_INV_CMD      0x400u  /* inverter command (byte0==1 act) */

/*
 * 0x351 — charge/discharge limits.  DLC 8, little-endian. (FUN_0002a0bc)
 *   [0:1] u16 charge voltage limit   x0.1 V  (model-selected; 51.2V pack=56.0V,
 *                                             25.6V=28.0V, 12.8V=14.0V)
 *   [2:3] u16 max charge current     x0.1 A  (getter FUN_00029338 * 10, <=3000.0A)
 *   [4:5] u16 max discharge current  x0.1 A  (getter FUN_0002935c * 10, <=3000.0A)
 *   [6:7] u16 discharge voltage limit x0.1 V (model-selected; 51.2V pack=45.0V)
 */
typedef struct {
    uint16_t charge_voltage_limit;   /* 0.1 V */
    uint16_t max_charge_current;     /* 0.1 A */
    uint16_t max_discharge_current;  /* 0.1 A */
    uint16_t discharge_voltage_limit;/* 0.1 V */
} bms_frame_351_t;

/*
 * 0x355 — state of charge / health.  DLC 6, little-endian. (FUN_0002a0bc)
 *   [0:1] u16 SOC  (%)              (getter FUN_000291f6)
 *   [2:3] u16 SOH  (%)              (getter FUN_00029380)
 *   [4:5] u16 SOC high-res          x0.01 % (= SOC * 100)
 */
typedef struct {
    uint16_t soc;        /* %      */
    uint16_t soh;        /* %      */
    uint16_t soc_hires;  /* 0.01 % */
} bms_frame_355_t;

/*
 * 0x356 — live measurements.  DLC 6, little-endian, signed. (FUN_0002a0bc)
 *   [0:1] s16 pack voltage   x0.01 V (getter FUN_000296f8)
 *   [2:3] s16 pack current   x0.1 A  (getter FUN_00029478; + = charge)
 *   [4:5] s16 temperature    x0.1 degC(getter FUN_000296b4/296f8 * 10)
 */
typedef struct {
    int16_t voltage;      /* 0.01 V  */
    int16_t current;      /* 0.1 A   */
    int16_t temperature;  /* 0.1 degC*/
} bms_frame_356_t;

/*
 * 0x359 / 0x35A — protection & alarm bitfields.  PARTIAL (positions recovered
 * from the FUN_0002a0bc OR-mask sequence; exact standard-bit assignment TBC).
 * Byte 0 collects protection bits (over/under V, over-current, over-temp),
 * byte 1 collects warning bits; a module/pack count and the ASCII marker "PN"
 * follow per the standard 0x359 layout.
 */

#endif /* INV_BMS_CAN_MAP_H */
