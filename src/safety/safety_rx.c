/*
 * USART2 safety-CPU frame parser -> telemetry bank (docs/33, docs/39 T05).
 * See include/inv/safety_rx.h for the model and frame layout.
 *
 * Pure and host-testable. Mirrors the factory receive chain (docs/33 §1): the
 * assembler (SOF 0x49, len byte, < 0x40 cap), the CRC-16/MODBUS validator with the
 * checksum stored big-endian, the header distributor, and the tag sub-record parser
 * (§1a). The telemetry bank is written as native little-endian, exactly as
 * safety_cpu_publish() reads it back.
 */
#include "inv/safety_rx.h"
#include "inv/modbus.h"          /* inv_modbus_crc16 (poly 0xA001, init 0xFFFF) */

/* ---- field helpers (frame is big-endian; bank is native little-endian) ---- */
static uint16_t rd_be16(const uint8_t *b, uint16_t o)
{
    return (uint16_t)(((uint16_t)b[o] << 8) | b[o + 1]);
}
static uint32_t rd_be32(const uint8_t *b, uint16_t o)
{
    return ((uint32_t)b[o] << 24) | ((uint32_t)b[o + 1] << 16) |
           ((uint32_t)b[o + 2] << 8) | b[o + 3];
}

void inv_safety_rx_init(inv_safety_rx_t *st, uint8_t *bank)
{
    if (!st)
        return;
    st->bank = bank;
    st->idx = 0;
    st->expected = 0;
    st->mode = 0;
    st->fault = 0;
    st->warn = 0;
    st->frames_ok = 0;
    st->frames_badcrc = 0;
    st->frames_badtype = 0;
}

/* Store a native-LE u16 into the bank at `off`, iff [off,off+2) and the source
 * field [src,src+2) both lie inside the frame payload (before the 2 CRC bytes). */
#define PAYLOAD_END(st)   ((st)->expected - 2u)
#define IN_FRAME(st,o,w)  ((uint16_t)((o) + (w)) <= PAYLOAD_END(st))

static void put_le16(inv_safety_rx_t *st, uint16_t bank_off, uint16_t src_off)
{
    if (!st->bank || !IN_FRAME(st, src_off, 2) || bank_off + 1u >= SAFETY_BANK_SIZE)
        return;
    uint16_t v = rd_be16(st->buf, src_off);
    st->bank[bank_off]     = (uint8_t)(v & 0xFF);
    st->bank[bank_off + 1] = (uint8_t)(v >> 8);
}
static void put_u8(inv_safety_rx_t *st, uint16_t bank_off, uint16_t src_off)
{
    if (!st->bank || !IN_FRAME(st, src_off, 1) || bank_off >= SAFETY_BANK_SIZE)
        return;
    st->bank[bank_off] = st->buf[src_off];
}

/* Dispatch the tag sub-record at frame[+0x14] (docs/33 §1a). Unknown tags are a
 * no-op (the frame is still accepted). */
static void decode_tag(inv_safety_rx_t *st)
{
    if (!IN_FRAME(st, 0x14, 1))
        return;
    switch (st->buf[0x14]) {
    case 0:   /* identity + radiator temps + grid T */
        put_u8  (st, 0x02, 0x19);                 /* DSP FW version        -> HR10 low */
        put_u8  (st, 0x03, 0x15); put_u8(st, 0x04, 0x16);
        put_u8  (st, 0x05, 0x17); put_u8(st, 0x06, 0x18);   /* peer identity "ceaa" */
        put_le16(st, 0x1e, 0x20);                 /* radiator temp 1       -> IR 65 */
        put_le16(st, 0x1c, 0x22);                 /* radiator temp 2       -> IR 66 */
        put_le16(st, 0xb6, 0x24);                 /* grid voltage T        -> IR 14 */
        break;
    case 1:   /* battery + BUS voltages */
        put_le16(st, 0x0a, 0x15);                 /* inverter batt V       -> IR 107 */
        put_le16(st, 0x0e, 0x1b);                 /* BUS1                  -> IR 38 */
        put_le16(st, 0x10, 0x1d);                 /* BUS2                  -> IR 39 */
        put_le16(st, 0x12, 0x25);                 /* half-BUS              -> IR 120 */
        break;
    case 2:   /* grid / EPS / inverter block */
        put_le16(st, 0x20, 0x17);                 /* grid R                -> IR 12 */
        put_le16(st, 0x5e, 0x19);                 /* grid freq             -> IR 15 */
        put_le16(st, 0x22, 0x1b);                 /* EPS R                 -> IR 20 */
        put_le16(st, 0x60, 0x1d);                 /* EPS freq              -> IR 23 */
        put_le16(st, 0x24, 0x21);                 /* inverter current      -> IR 18 */
        put_le16(st, 0x28, 0x23);                 /* grid S                -> IR 13 */
        put_le16(st, 0x62, 0x25);                 /* generator freq        -> IR 122 */
        break;
    default:
        /* tag 3 (energy/power raws, not served IRs) and any unknown tag: accepted,
         * no measurement distribution (docs/33 §1a). */
        break;
    }
}

/* Decode a complete, CRC-valid, type-1 frame (buf[0..expected)) into the bank and
 * the header mode/fault/warn. */
static void decode_frame(inv_safety_rx_t *st)
{
    const uint8_t *b = st->buf;

    /* Header (fixed offsets). mode + relayed fault/warn feed the classifier. */
    if (IN_FRAME(st, 0x04, 1)) { st->mode = b[0x04]; put_u8(st, 0x00, 0x04); }
    if (IN_FRAME(st, 0x05, 4)) {
        st->fault = rd_be32(b, 0x05);
        if (0xd0u + 4u <= SAFETY_BANK_SIZE && st->bank) {
            st->bank[0xd0] = (uint8_t)(st->fault); st->bank[0xd1] = (uint8_t)(st->fault >> 8);
            st->bank[0xd2] = (uint8_t)(st->fault >> 16); st->bank[0xd3] = (uint8_t)(st->fault >> 24);
        }
    }
    if (IN_FRAME(st, 0x09, 4)) {
        st->warn = rd_be32(b, 0x09);
        if (0xd4u + 4u <= SAFETY_BANK_SIZE && st->bank) {
            st->bank[0xd4] = (uint8_t)(st->warn); st->bank[0xd5] = (uint8_t)(st->warn >> 8);
            st->bank[0xd6] = (uint8_t)(st->warn >> 16); st->bank[0xd7] = (uint8_t)(st->warn >> 24);
        }
    }
    put_u8  (st, 0x01, 0x0d);                      /* secondary mode byte */
    put_le16(st, 0xc4, 0x0f);                      /* -> IR 94 */
    /* bank+0xca = frame[+0x11] (lo) | frame[+0x12] (hi) -- NOT big-endian (docs/33) */
    if (IN_FRAME(st, 0x11, 2) && st->bank && 0xcbu < SAFETY_BANK_SIZE) {
        st->bank[0xca] = b[0x11];
        st->bank[0xcb] = b[0x12];
    }
    put_u8  (st, 0xe0, 0x13);

    decode_tag(st);
}

inv_safety_rx_evt_t inv_safety_rx_byte(inv_safety_rx_t *st, uint8_t b)
{
    if (!st)
        return SAFETY_RX_NONE;

    /* Overflow guard: a frame can never exceed the assembler cap. */
    if (st->idx >= SAFETY_RX_MAXLEN)
        st->idx = 0;

    switch (st->idx) {
    case 0:                                   /* SOF */
        if (b != SAFETY_RX_SOF)
            return SAFETY_RX_NONE;            /* discard bytes until a SOF (resync) */
        st->buf[0] = b; st->idx = 1;
        return SAFETY_RX_NONE;
    case 1:                                   /* type (checked at completion) */
        st->buf[1] = b; st->idx = 2;
        return SAFETY_RX_NONE;
    case 2:                                   /* seq/flags */
        st->buf[2] = b; st->idx = 3;
        return SAFETY_RX_NONE;
    case 3: {                                 /* length -> total frame size */
        uint16_t total = (uint16_t)b + 6u;
        if (total < 7u || total > SAFETY_RX_MAXLEN) {
            /* bad length: resync (treat this byte as a possible SOF next) */
            st->idx = 0;
            return SAFETY_RX_NONE;
        }
        st->buf[3] = b;
        st->expected = total;
        st->idx = 4;
        return SAFETY_RX_NONE;
    }
    default:
        st->buf[st->idx++] = b;
        if (st->idx < st->expected)
            return SAFETY_RX_NONE;
        break;                                /* frame complete */
    }

    /* Complete frame in buf[0..expected). Reset the assembler first. */
    uint16_t n = st->expected;
    st->idx = 0;
    st->expected = 0;

    /* CRC-16/MODBUS over [0..n-2), stored big-endian (MSB first) at [n-2],[n-1]. */
    uint16_t calc = inv_modbus_crc16(st->buf, (size_t)(n - 2));
    uint16_t rx   = (uint16_t)(((uint16_t)st->buf[n - 2] << 8) | st->buf[n - 1]);
    if (calc != rx) {
        st->frames_badcrc++;
        return SAFETY_RX_BADCRC;
    }
    if (st->buf[1] != SAFETY_RX_TYPE1) {
        st->frames_badtype++;
        return SAFETY_RX_BADTYPE;
    }

    st->expected = n;            /* so IN_FRAME() in the decoders sees the length */
    decode_frame(st);
    st->expected = 0;
    st->frames_ok++;
    return SAFETY_RX_FRAME;
}

uint32_t inv_safety_rx_feed(inv_safety_rx_t *st, const uint8_t *buf, uint32_t len)
{
    uint32_t frames = 0;
    for (uint32_t i = 0; i < len; i++)
        if (inv_safety_rx_byte(st, buf[i]) == SAFETY_RX_FRAME)
            frames++;
    return frames;
}
