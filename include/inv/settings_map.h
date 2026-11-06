/*
 * Pinned settings table — which holding registers persist to the config flash,
 * and where (docs/23 field map; task T03 in docs/39).
 *
 * Each entry maps a Modbus holding register to a (slot, byte-offset, width,
 * scale) location in the factory's 250-byte slot payload. The on-flash format is
 * byte-compatible with the factory (docs/21, docs/23, inv/config_flash.h), so a
 * record written here is read correctly by the factory firmware and vice-versa.
 * Proven both directions by tests/test_persist_crossimage.py, which shares the
 * SAME table via tests/settings_persist_contract.py.
 *
 * WIDTH is the on-flash stored width in bytes. docs/23 first recorded the whole
 * map as "2B", but the factory oracle shows slot-5's power-command block
 * (+0x00..+0x07) is a packed run of 1-byte fields; those rows are width 1 here
 * (docs/23 "Width correction"). SCALE is the factor the wire value is multiplied
 * by before storing: the factory stores ChargeCurr/DischgCurr/MaxBackFlow x10,
 * everything else x1.
 */
#ifndef INV_SETTINGS_MAP_H
#define INV_SETTINGS_MAP_H

#include <stdint.h>

typedef struct {
    uint16_t reg;     /* Modbus holding register                         */
    uint8_t  slot;    /* config-flash slot (0 main, 5 grid/protection)   */
    uint8_t  off;     /* byte offset into the slot's 250-byte payload    */
    uint8_t  width;   /* stored width: 1 or 2 bytes                      */
    uint8_t  scale;   /* wire * scale = stored (1, or 10 for the x10 set)*/
} settings_field_t;

/* Keep in lockstep with tests/settings_persist_contract.py (the cross-image
 * test enforces it). 56 registers pinned dynamically in docs/23. */
static const settings_field_t SETTINGS_MAP[] = {
    /* slot 0 — main inverter / working settings (width 2) */
    {  15, 0, 0x00, 2, 1  },   /* ComAddr                    */
    {  21, 0, 0x13, 2, 1  },   /* FuncEn (bitmask)           */
    { 110, 0, 0x15, 2, 1  },   /* FunctionEn1 (bitmask)      */
    {  20, 0, 0x18, 2, 1  },   /* PVInputModel               */
    { 112, 0, 0x1b, 2, 1  },   /* SetSystemType              */
    { 119, 0, 0x2f, 2, 1  },   /* wCT_PowerOffset            */
    { 120, 0, 0x33, 2, 1  },   /* stSysEnable (bitmask)      */
    {  68, 0, 0x3a, 2, 1  },   /* ACChgStart                 */
    {  69, 0, 0x3c, 2, 1  },   /* ACChgEnd                   */
    {  70, 0, 0x3e, 2, 1  },   /* ACChgStart1                */
    {  71, 0, 0x40, 2, 1  },   /* ACChgEnd1                  */
    {  72, 0, 0x42, 2, 1  },   /* ACChgStart2                */
    {  73, 0, 0x44, 2, 1  },   /* ACChgEnd2                  */
    { 147, 0, 0x70, 2, 1  },   /* Battery capacity           */
    {  99, 0, 0x74, 2, 1  },   /* ChargeVoltRef (lead-acid)  */
    { 151, 0, 0x7c, 2, 1  },   /* EqualizationTime           */
    { 101, 0, 0x8c, 2, 10 },   /* ChargeCurr   (A, x10)      */
    { 102, 0, 0x8e, 2, 10 },   /* DischgCurr   (A, x10)      */
    { 103, 0, 0x9c, 2, 10 },   /* MaxBackFlow  (%, x10)      */
    { 105, 0, 0x9e, 2, 1  },   /* EOD                        */
    { 107, 0, 0xa1, 2, 1  },   /* TemprUpperLimitDischg      */
    { 109, 0, 0xa5, 2, 1  },   /* TemprUpperLimitChg (docs/23 +0xa4 was wrong) */
    { 152, 0, 0x64, 2, 1  },   /* ACFirstStart0 (T03 probe; not in docs/23 table) */
    { 153, 0, 0x66, 2, 1  },   /* ACFirstEnd0                */
    { 154, 0, 0x68, 2, 1  },   /* ACFirstStart1              */
    { 155, 0, 0x6a, 2, 1  },   /* ACFirstEnd1                */
    { 156, 0, 0x6c, 2, 1  },   /* ACFirstStart2              */
    { 157, 0, 0x6e, 2, 1  },   /* ACFirstEnd2                */

    /* slot 5 — packed power-command block (width 1, +0x00..+0x07) */
    {  60, 5, 0x00, 1, 1  },   /* ActivePowerPercentCMD      */
    {  61, 5, 0x01, 1, 1  },   /* ReactivePowerPercentCMD    */
    {  64, 5, 0x02, 1, 1  },   /* ChargePowerPercentCMD      */
    {  65, 5, 0x03, 1, 1  },   /* DischgPowerPercentCMD      */
    {  66, 5, 0x04, 1, 1  },   /* ACChgPowerCMD              */
    {  23, 5, 0x05, 1, 1  },   /* ConnectTime (1-byte store) */
    {  59, 5, 0x07, 1, 1  },   /* ReactivePowerCMDType       */

    /* slot 5 — grid-code protection block (width 2, +0x0a..) */
    {  30, 5, 0x0a, 2, 1  },   /* GridVoltLimit1High         */
    {  34, 5, 0x0c, 2, 1  },   /* GridVoltLimit2High         */
    {  38, 5, 0x0e, 2, 1  },   /* GridVoltLimit3High         */
    {  29, 5, 0x10, 2, 1  },   /* GridVoltLimit1Low          */
    {  33, 5, 0x12, 2, 1  },   /* GridVoltLimit2Low          */
    {  37, 5, 0x14, 2, 1  },   /* GridVoltLimit3Low          */
    {  32, 5, 0x16, 2, 1  },   /* GridVoltLimit1HighTime     */
    {  36, 5, 0x18, 2, 1  },   /* GridVoltLimit2HighTime     */
    {  40, 5, 0x1a, 2, 1  },   /* GridVoltLimit3HighTime     */
    {  31, 5, 0x1c, 2, 1  },   /* GridVoltLimit1LowTime      */
    {  35, 5, 0x1e, 2, 1  },   /* GridVoltLimit2LowTime      */
    {  39, 5, 0x20, 2, 1  },   /* GridVoltLimit3LowTime      */
    {  43, 5, 0x22, 2, 1  },   /* GridFreqLimit1High         */
    {  47, 5, 0x24, 2, 1  },   /* GridFreqLimit2High         */
    {  51, 5, 0x26, 2, 1  },   /* GridFreqLimit3High         */
    {  46, 5, 0x2a, 2, 1  },   /* GridFreqLimit2Low          */
    {  45, 5, 0x2e, 2, 1  },   /* GridFreqLimit1HighTime     */
    {  49, 5, 0x30, 2, 1  },   /* GridFreqLimit2HighTime     */
    {  53, 5, 0x32, 2, 1  },   /* GridFreqLimit3HighTime     */
    {  44, 5, 0x34, 2, 1  },   /* GridFreqLimit1LowTime      */
    {  48, 5, 0x36, 2, 1  },   /* GridFreqLimit2LowTime      */
    {  52, 5, 0x38, 2, 1  },   /* GridFreqLimit3LowTime      */
    {  26, 5, 0x3a, 2, 1  },   /* GridVoltConnHigh           */
    {  25, 5, 0x3c, 2, 1  },   /* GridVoltConnLow            */
    {  28, 5, 0x3e, 2, 1  },   /* GridFreqConnHigh           */
    {  27, 5, 0x40, 2, 1  },   /* GridFreqConnLow            */
    {  75, 5, 0x7a, 2, 1  },   /* ChgFirstSOCLimit           */
};

#define SETTINGS_MAP_LEN (sizeof(SETTINGS_MAP) / sizeof(SETTINGS_MAP[0]))

#endif /* INV_SETTINGS_MAP_H */
