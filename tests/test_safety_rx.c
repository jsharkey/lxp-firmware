/* Host tests for the USART2 safety-CPU frame parser (docs/39 T05). make test */
#include "inv/safety_rx.h"
#include "inv/safety_cpu.h"
#include "inv/modbus.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

/* Build an EG4 type-1 frame: SOF 0x49, type, [2]=0, len=total-6, payload set by
 * `fields` (big-endian), CRC-16/MODBUS over [0..total-2) stored MSB-first. */
typedef struct { uint16_t off, width; uint32_t val; } field_t;

static uint16_t build(uint8_t *f, uint16_t total, uint8_t type,
                      const field_t *fields, int nf)
{
    memset(f, 0, total);
    f[0] = 0x49; f[1] = type; f[2] = 0; f[3] = (uint8_t)(total - 6);
    for (int i = 0; i < nf; i++) {
        uint16_t o = fields[i].off, w = fields[i].width;
        for (uint16_t k = 0; k < w; k++)             /* big-endian */
            f[o + k] = (uint8_t)(fields[i].val >> (8 * (w - 1 - k)));
    }
    uint16_t crc = inv_modbus_crc16(f, (size_t)(total - 2));
    f[total - 2] = (uint8_t)(crc >> 8);              /* MSB first */
    f[total - 1] = (uint8_t)(crc & 0xFF);
    return total;
}

static uint16_t bank16(const uint8_t *bank, uint16_t off)
{
    return (uint16_t)(bank[off] | ((uint16_t)bank[off + 1] << 8));
}

int main(void)
{
    uint8_t bank[SAFETY_BANK_SIZE];
    uint8_t f[SAFETY_RX_MAXLEN];
    inv_safety_rx_t st;

    /* --- good tag-2 frame: grid/EPS/inverter measurements land in the bank --- */
    {
        field_t fs[] = {
            {0x04, 1, 0x04},            /* mode = PV on-grid */
            {0x05, 4, 0x00080000u},     /* relayed fault (E019 bit 19) */
            {0x09, 4, 0x00000400u},     /* relayed warn  (bit 10) */
            {0x14, 1, 2},               /* tag 2 */
            {0x17, 2, 2401}, {0x19, 2, 5001}, {0x1b, 2, 2399},
            {0x1d, 2, 5000}, {0x21, 2, 1234}, {0x23, 2, 2402}, {0x25, 2, 6000},
        };
        uint16_t n = build(f, 0x3e, 1, fs, (int)(sizeof fs / sizeof fs[0]));
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "good frame: 1 frame decoded");
        CHECK(st.frames_ok == 1 && st.frames_badcrc == 0, "good frame: stats");
        CHECK(st.mode == 0x04, "good frame: mode byte");
        CHECK(st.fault == 0x00080000u, "good frame: relayed fault BE32");
        CHECK(st.warn == 0x00000400u, "good frame: relayed warn BE32");
        CHECK(bank16(bank, SAFETY_OFF_VAC_R) == 2401, "tag2 -> grid R (bank+0x20)");
        CHECK(bank16(bank, SAFETY_OFF_FAC)   == 5001, "tag2 -> grid freq (bank+0x5e)");
        CHECK(bank16(bank, SAFETY_OFF_VEPS_R) == 2399, "tag2 -> EPS R (bank+0x22)");
        CHECK(bank16(bank, SAFETY_OFF_FEPS)  == 5000, "tag2 -> EPS freq (bank+0x60)");
        CHECK(bank16(bank, SAFETY_OFF_IINV)  == 1234, "tag2 -> inverter current (bank+0x24)");
        CHECK(bank16(bank, SAFETY_OFF_VAC_S) == 2402, "tag2 -> grid S (bank+0x28)");
        CHECK(bank16(bank, SAFETY_OFF_GEN_FREQ) == 6000, "tag2 -> generator freq (bank+0x62)");
    }

    /* --- tag-0: identity + radiator temps + grid T --- */
    {
        field_t fs[] = {
            {0x14, 1, 0},
            {0x15, 1, 'c'}, {0x16, 1, 'e'}, {0x17, 1, 'a'}, {0x18, 1, 'a'},
            {0x19, 1, 0x05},            /* DSP FW version */
            {0x20, 2, 275}, {0x22, 2, 260}, {0x24, 2, 2300},
        };
        uint16_t n = build(f, 0x30, 1, fs, (int)(sizeof fs / sizeof fs[0]));
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "tag0: 1 frame decoded");
        CHECK(bank[0x02] == 0x05, "tag0 -> DSP FW version (bank+2)");
        CHECK(memcmp(bank + 3, "ceaa", 4) == 0, "tag0 -> peer identity (bank+3..6)");
        CHECK(bank16(bank, SAFETY_OFF_T_RAD1) == 275, "tag0 -> radiator 1 (bank+0x1e)");
        CHECK(bank16(bank, SAFETY_OFF_T_RAD2) == 260, "tag0 -> radiator 2 (bank+0x1c)");
        CHECK(bank16(bank, SAFETY_OFF_VAC_T) == 2300, "tag0 -> grid T (bank+0xb6)");
    }

    /* --- tag-1: battery + BUS voltages --- */
    {
        field_t fs[] = {
            {0x14, 1, 1},
            {0x15, 2, 532}, {0x1b, 2, 3900}, {0x1d, 2, 3901}, {0x25, 2, 1950},
        };
        uint16_t n = build(f, 0x30, 1, fs, (int)(sizeof fs / sizeof fs[0]));
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "tag1: 1 frame decoded");
        CHECK(bank16(bank, SAFETY_OFF_VBUS1)  == 3900, "tag1 -> BUS1 (bank+0x0e)");
        CHECK(bank16(bank, SAFETY_OFF_VBUS2)  == 3901, "tag1 -> BUS2 (bank+0x10)");
        CHECK(bank16(bank, SAFETY_OFF_VBUS_P) == 1950, "tag1 -> half-BUS (bank+0x12)");
        CHECK(bank16(bank, 0x0a) == 532, "tag1 -> inverter batt V (bank+0x0a)");
    }

    /* --- bad CRC: dropped, bank untouched --- */
    {
        field_t fs[] = { {0x14, 1, 2}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 1, fs, 2);
        f[n - 1] ^= 0xFF;                     /* corrupt the checksum */
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n) == 0, "bad CRC: no frame");
        CHECK(st.frames_badcrc == 1 && st.frames_ok == 0, "bad CRC: stats");
        CHECK(bank16(bank, SAFETY_OFF_VAC_R) == 0, "bad CRC: bank untouched");
    }

    /* --- wrong type byte: rejected after CRC --- */
    {
        field_t fs[] = { {0x14, 1, 2}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 2 /* type != 1 */, fs, 2);
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        inv_safety_rx_evt_t last = SAFETY_RX_NONE;
        for (uint16_t i = 0; i < n; i++) last = inv_safety_rx_byte(&st, f[i]);
        CHECK(last == SAFETY_RX_BADTYPE, "wrong type: BADTYPE");
        CHECK(st.frames_ok == 0 && st.frames_badtype == 1, "wrong type: stats");
    }

    /* --- truncated frame: no completion --- */
    {
        field_t fs[] = { {0x14, 1, 2}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 1, fs, 2);
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n - 3) == 0, "truncated: no frame");
        CHECK(st.frames_ok == 0, "truncated: stats");
    }

    /* --- unknown tag: frame accepted, header decoded, no measurement change --- */
    {
        field_t fs[] = { {0x04, 1, 0x10}, {0x14, 1, 0x7f}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 1, fs, 3);
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "unknown tag: frame accepted");
        CHECK(st.mode == 0x10, "unknown tag: header mode still decoded");
        CHECK(bank16(bank, SAFETY_OFF_VAC_R) == 0, "unknown tag: no measurement distributed");
    }

    /* --- resync after garbage: junk then a clean frame --- */
    {
        field_t fs[] = { {0x14, 1, 2}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 1, fs, 2);
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        uint8_t junk[] = {0x00, 0xFF, 0x12, 0x34, 0xAB, 0x00, 0x7E};   /* no SOF */
        inv_safety_rx_feed(&st, junk, sizeof junk);
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "resync: clean frame after junk");
        CHECK(bank16(bank, SAFETY_OFF_VAC_R) == 2401, "resync: measurement decoded");
    }

    /* --- resync after a bad-CRC frame: next good frame still parses --- */
    {
        field_t fs[] = { {0x14, 1, 2}, {0x17, 2, 2401} };
        uint16_t n = build(f, 0x30, 1, fs, 2);
        memset(bank, 0, sizeof bank);
        inv_safety_rx_init(&st, bank);
        uint8_t bad[SAFETY_RX_MAXLEN];
        memcpy(bad, f, n); bad[n - 1] ^= 0xFF;
        inv_safety_rx_feed(&st, bad, n);          /* bad CRC frame */
        CHECK(inv_safety_rx_feed(&st, f, n) == 1, "resync: good frame after bad-CRC frame");
        CHECK(st.frames_ok == 1 && st.frames_badcrc == 1, "resync: stats");
    }

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
