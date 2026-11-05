/*
 * Battery BMS CAN decoder — transport-agnostic (host-testable, no hardware).
 * Turns a received frame into decoded pack state per include/inv/bms_can_map.h
 * (standard little-endian preset). See docs/20.
 */
#include "inv/bms_can.h"
#include "inv/bms_can_map.h"
#include <string.h>

static inline uint16_t rd_le16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

void bms_can_init(bms_pack_t *pack)
{
    memset(pack, 0, sizeof *pack);
}

bool bms_can_on_frame(bms_pack_t *pack, uint32_t id, const uint8_t *data, uint8_t dlc)
{
    switch (id) {
    case BMS_CAN_ID_SOC_SOH:            /* 0x355: [0:1] SOC %, [2:3] SOH % */
        if (dlc < 4) return false;
        pack->soc = (uint8_t)rd_le16(data);
        pack->soh = (uint8_t)rd_le16(data + 2);
        pack->soc_soh_valid = true;
        return true;
    case BMS_CAN_ID_VIT:                /* 0x356: [0:1] V, [2:3] I, [4:5] T (signed) */
        if (dlc < 6) return false;
        pack->voltage_cv = (int16_t)rd_le16(data);
        pack->current_ca = (int16_t)rd_le16(data + 2);
        pack->temp_dc    = (int16_t)rd_le16(data + 4);
        pack->measured_valid = true;
        return true;
    case BMS_CAN_ID_LIMITS:             /* 0x351: [0:1] charge voltage limit */
        if (dlc < 2) return false;
        pack->charge_volt_dv = rd_le16(data);
        pack->limits_valid = true;
        return true;
    case BMS_CAN_ID_ALARM_A:           /* 0x359: [0:1] protection, [2:3] alarm */
        if (dlc < 4) return false;
        pack->fault_bits = rd_le16(data);
        pack->warn_bits  = rd_le16(data + 2);
        pack->alarms_valid = true;
        return true;
        /* 0x35A (ALARM_B) is received by the factory but not published to any
         * Modbus register (see docs/29), so we don't consume it. */
    default:
        return false;                   /* other telemetry IDs not consumed yet */
    }
}
