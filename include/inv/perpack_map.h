/*
 * Per-pack battery telemetry — undocumented Modbus input registers 5000-5126.
 * (docs/34 §2b; factory getter sub_08020cc0, CAN parser sub_080205d4.)
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
 * WHAT IS NOT YET CONFIRMED: the physical MEANING of each field. The parser is a
 * straight byte copy, so semantics live in the battery's frame definitions, which
 * need the battery image or a live CAN capture to pin (not available here). Field
 * names below are therefore STRUCTURAL (subtype + word index), not semantic. See
 * docs/34 §2b for the inference method and the candidate quantity set.
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
    PP_S0_W0 =  0,   /* CAN 0x400 subtype0 bytes[0:1] */
    PP_S0_W1 =  1,   /* CAN 0x400 subtype0 bytes[2:3] */
    PP_S0_W2 =  2,   /* CAN 0x400 subtype0 lo=byte4, hi=byte7 (split pair) */
    PP_S0_W3 =  3,   /* CAN 0x400 subtype0 bytes[5:6] */
    PP_S1_W0 =  4,   /* CAN 0x420 subtype1 bytes[0:1] */
    PP_S1_W1 =  5,   /* CAN 0x420 subtype1 bytes[2:3] */
    PP_S1_W2 =  6,   /* CAN 0x420 subtype1 bytes[4:5] */
    PP_S1_W3 =  7,   /* CAN 0x420 subtype1 bytes[6:7] */
    PP_S2_W0 =  8,   /* CAN 0x440 subtype2 bytes[0:1] */
    PP_S2_W1 =  9,   /* CAN 0x440 subtype2 bytes[2:3] */
    PP_S2_W2 = 10,   /* CAN 0x440 subtype2 bytes[4:5] */
    PP_S2_W3 = 11,   /* CAN 0x440 subtype2 bytes[6:7] */
    PP_S3_W0 = 12,   /* CAN 0x460 subtype3 bytes[0:1] */
    PP_S3_W1 = 13,   /* CAN 0x460 subtype3 bytes[2:3] */
    PP_S3_W2 = 14,   /* CAN 0x460 subtype3 bytes[4:5] */
    PP_S3_W3 = 15,   /* CAN 0x460 subtype3 bytes[6:7] */
    PP_S4_W0 = 16,   /* CAN 0x480 subtype4 bytes[0:1] */
    PP_S4_W1 = 17,   /* CAN 0x480 subtype4 bytes[2:3] */
    PP_S4_W2 = 18,   /* CAN 0x480 subtype4 bytes[4:5] */
    PP_S5_W0 = 19,   /* CAN 0x4A0 subtype5 bytes[0:1] */
    PP_S5_W1 = 20,   /* CAN 0x4A0 subtype5 bytes[2:3] */
    PP_S5_W2 = 21,   /* CAN 0x4A0 subtype5 bytes[4:5] */
    PP_S5_W3 = 22,   /* CAN 0x4A0 subtype5 bytes[6:7] */
    PP_S6_W0 = 23,   /* CAN 0x4C0 subtype6 bytes[0:1] */
    PP_S6_W1 = 24,   /* CAN 0x4C0 subtype6 bytes[2:3] */
    PP_S6_W2 = 25,   /* CAN 0x4C0 subtype6 bytes[4:5] */
    PP_S6_W3 = 26    /* CAN 0x4C0 subtype6 byte[6]   (u8; high byte 0) */
};

/* One pack's served record. Index with enum pp_field; all native u16 as served. */
typedef struct {
    uint16_t field[IR_PERPACK_FIELDS];
} pp_pack_record_t;

#endif /* INV_PERPACK_MAP_H */
