/*
 * Per-pack battery telemetry — undocumented Modbus input registers 5000-5126.
 * (docs/34 §2b; factory getter sub_08020cc0, CAN parser sub_080205d4.)
 *
 * NOTE — fed by CAN 0x4xx; LIVE on a 0x4xx pack, dormant on EG4-LL. This bank is
 * served from a per-pack array filled ONLY by CAN 0x4xx frames (sub_080205d4). The
 * EG4-LL battery emits per-pack/extended telemetry on 0x3xx (0x311-0x321, 0x370-0x381),
 * which the ARM parses to internal scalars NOT read by the Modbus getter -- so this
 * bank stays empty with that pack (docs/34 §2b). A pack that natively speaks the
 * 0x4xx per-pack (Pylontech-family) protocol DOES populate it: a production-12000XP
 * capture shows two such packs decoded live (docs/34 §2d), which also pins the field
 * semantics annotated in the enum below.
 *
 * Beyond the aggregate BMS block (IR 81-106), the factory serves PER-PACK battery
 * telemetry on a separate high register range that no public EG4 map lists. The
 * data arrives on CAN as
 *
 *     id = 0x400 | (subtype << 5) | pack      // pack = low 5 bits (0..31),
 *                                             // subtype = bits 5..7 (0..6 used)
 *
 * and the parser copies each subtype frame's bytes, LITTLE-ENDIAN and UNSCALED,
 * into a per-pack array (one 27 x u16 record per pack, stride 0x36). The Modbus
 * getter then serves 30 register slots per pack, four packs per poll at bases
 * 5000 / 5030 / 5060 / 5090, paging a window index for >4 packs.
 *
 * WHAT IS AUTHORITATIVE HERE: the register addressing and each field's byte
 * provenance (subtype + frame bytes), recovered from the firmware and verified in
 * the harness (tests/test_arm_sim_factory_only.py::test_per_pack_telemetry_reaches_modbus).
 *
 * FIELD MEANING: now pinned by a production-12000XP capture (docs/34 §2d), which
 * carries the live register values. The structural PP_S<sub>_W<word> names stay as
 * the stable index; each field's confirmed meaning is in the trailing comment.
 * Meanings tagged [xref IRnn] are cross-checked against a known-scale aggregate
 * register in the same capture; others are the best read from magnitude ("prob.").
 */
#ifndef INV_PERPACK_MAP_H
#define INV_PERPACK_MAP_H

#include <stdint.h>

/* CAN id that carries pack `p`, subtype `s` (s = 0..6). */
#define PERPACK_CAN_BASE        0x400u
#define PERPACK_CAN_ID(s, p)    (PERPACK_CAN_BASE | (((s) & 0x7u) << 5) | ((p) & 0x1Fu))

/* Input-register addressing. */
#define IR_PERPACK_BASE     5000u   /* first per-pack input register               */
#define IR_PERPACK_STRIDE   30u     /* register slots per pack (bases 5000/30/60/90)*/
#define IR_PERPACK_FIELDS   27u     /* u16 fields populated per pack                */
#define IR_PERPACK_MAX      5126u   /* last register of the range                   */
#define IR_PERPACK_MAX_PACKS 32u    /* pack index is 5 bits                         */

/* Input register for pack `p` (0-based), field index `f` (0..26). */
#define IR_PERPACK(p, f)    (IR_PERPACK_BASE + IR_PERPACK_STRIDE * (p) + (f))

/*
 * Field index within a pack's record, named STRUCTURALLY as PP_S<subtype>_W<word>.
 * The comment gives the source CAN subtype frame bytes (all little-endian u16,
 * except PP_S0_W2 which is a split pair lo=byte4/hi=byte7, and PP_S6_W3 which is a
 * single byte with the high byte 0). "field index" is also "register - 5000" for
 * the pack at base 5000.
 */
enum pp_field {
    PP_S0_W0 =  0,   /* 0x400 s0 b[0:1]  -- (zero in capture) */
    PP_S0_W1 =  1,   /* 0x400 s0 b[2:3]  -- (zero in capture) */
    PP_S0_W2 =  2,   /* 0x400 s0 lo=b4,hi=b7 (split) -- status/flags (0xc002) */
    PP_S0_W3 =  3,   /* 0x400 s0 b[5:6]  -- charge-current limit, prob. (0.1 A) */
    PP_S1_W0 =  4,   /* 0x420 s1 b[0:1]  -- charge-voltage ref, 0.1 V [xref IR83] */
    PP_S1_W1 =  5,   /* 0x420 s1 b[2:3]  -- discharge-current limit, prob. (0.1 A) */
    PP_S1_W2 =  6,   /* 0x420 s1 b[4:5]  -- limit, prob. */
    PP_S1_W3 =  7,   /* 0x420 s1 b[6:7]  -- limit, prob. */
    PP_S2_W0 =  8,   /* 0x440 s2 b[0:1]  -- pack voltage, 0.01 V [xref IR4@0.1V] */
    PP_S2_W1 =  9,   /* 0x440 s2 b[2:3]  -- pack current, signed 0.1 A */
    PP_S2_W2 = 10,   /* 0x440 s2 b[4:5]  -- SOC(lo)|SOH(hi), % [xref IR5] */
    PP_S2_W3 = 11,   /* 0x440 s2 b[6:7]  -- cycle count, prob. */
    PP_S3_W0 = 12,   /* 0x460 s3 b[0:1]  -- max cell temp [xref IR103] */
    PP_S3_W1 = 13,   /* 0x460 s3 b[2:3]  -- min cell temp [xref IR104] */
    PP_S3_W2 = 14,   /* 0x460 s3 b[4:5]  -- max cell voltage, mV [xref IR101] */
    PP_S3_W3 = 15,   /* 0x460 s3 b[6:7]  -- min cell voltage, mV [xref IR102] */
    PP_S4_W0 = 16,   /* 0x480 s4 b[0:1]  -- status/flags (differs per pack) */
    PP_S4_W1 = 17,   /* 0x480 s4 b[2:3]  -- firmware/version (0x0101) */
    PP_S4_W2 = 18,   /* 0x480 s4 b[4:5]  -- version/protocol (0x0203) */
    PP_S5_W0 = 19,   /* 0x4A0 s5 b[0:1]  -- ASCII pack id "Battery_ID_0N" (from CAN) */
    PP_S5_W1 = 20,   /* 0x4A0 s5 b[2:3]  -- ASCII pack id (cont.) */
    PP_S5_W2 = 21,   /* 0x4A0 s5 b[4:5]  -- ASCII pack id (cont.) */
    PP_S5_W3 = 22,   /* 0x4A0 s5 b[6:7]  -- ASCII pack id (cont.) */
    PP_S6_W0 = 23,   /* 0x4C0 s6 b[0:1]  -- ASCII pack id (cont.) */
    PP_S6_W1 = 24,   /* 0x4C0 s6 b[2:3]  -- ASCII pack id (cont.) */
    PP_S6_W2 = 25,   /* 0x4C0 s6 b[4:5]  -- ASCII pack id (tail) */
    PP_S6_W3 = 26    /* 0x4C0 s6 b[6]    -- u8; string tail / zero */
};

/* One pack's served record. Index with enum pp_field; all native u16 as served. */
typedef struct {
    uint16_t field[IR_PERPACK_FIELDS];
} pp_pack_record_t;

#endif /* INV_PERPACK_MAP_H */
