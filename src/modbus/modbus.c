/*
 * Modbus-RTU slave engine (EG4/Luxpower variant). Transport-agnostic core.
 * See include/inv/modbus.h for the framing contract.
 */
#include "inv/modbus.h"
#include "inv/modbus_map.h"
#include <string.h>

/* fixed field offsets common to every frame */
#define OFF_ADDR   0
#define OFF_FUNC   1
#define OFF_SN     2
#define OFF_BODY   (OFF_SN + MB_SN_LEN)   /* 12: first byte after SN */

uint16_t inv_modbus_crc16(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int b = 0; b < 8; b++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
    return crc;
}

static inline uint16_t rd_le16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline void     wr_le16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

/* append CRC (lo,hi) over resp[0..len) and return total length */
static size_t finish(uint8_t *resp, size_t len)
{
    uint16_t crc = inv_modbus_crc16(resp, len);
    wr_le16(resp + len, crc);
    return len + 2;
}

/* build an exception response: addr (func|0x80) SN start(2) excCode CRC */
static size_t make_exception(const mb_config_t *cfg, uint8_t func,
                             uint16_t start, mb_exception_t exc, uint8_t *resp)
{
    resp[OFF_ADDR] = cfg->address;
    resp[OFF_FUNC] = (uint8_t)(func | 0x80);
    memcpy(resp + OFF_SN, cfg->sn, MB_SN_LEN);
    wr_le16(resp + OFF_BODY, start);
    resp[OFF_BODY + 2] = (uint8_t)exc;
    return finish(resp, OFF_BODY + 3);
}

/* validate the 40-register group rule: <=40 regs and no group-boundary crossing */
static bool query_span_ok(uint16_t start, uint16_t n)
{
    if (n == 0 || n > MB_MAX_REGS_PER_QUERY) return false;
    return (start / MB_MAX_REGS_PER_QUERY) == ((uint16_t)(start + n - 1) / MB_MAX_REGS_PER_QUERY);
}

size_t inv_modbus_process(const mb_config_t *cfg,
                          const uint8_t *req, size_t req_len,
                          uint8_t *resp, size_t resp_cap)
{
    /* smallest valid frame: addr+func+SN+CRC = 14; real ones are longer */
    if (req_len < OFF_BODY + 2) return 0;
    if (resp_cap < MB_FRAME_MAX) return 0;

    /* CRC check (covers everything but the trailing 2 CRC bytes) */
    uint16_t rx_crc = rd_le16(req + req_len - 2);
    if (inv_modbus_crc16(req, req_len - 2) != rx_crc) return 0;

    /* address filter (accept our address; broadcast only meaningful for writes) */
    uint8_t addr = req[OFF_ADDR];
    if (addr != cfg->address && addr != MB_ADDR_BROADCAST) return 0;

    /* optional serial-number targeting */
    if (cfg->check_sn && memcmp(req + OFF_SN, cfg->sn, MB_SN_LEN) != 0) return 0;

    const uint8_t func = req[OFF_FUNC];
    const uint8_t *body = req + OFF_BODY;        /* fields after SN */
    const size_t  body_len = req_len - OFF_BODY - 2;

    switch (func) {
    case MB_FC_READ_INPUT:      /* 0x04 */
    case MB_FC_READ_HOLDING: {  /* 0x03 */
        if (body_len < 4) return make_exception(cfg, func, 0, MB_EXC_ILLEGAL_VALUE, resp);
        uint16_t start = rd_le16(body);
        uint16_t n     = rd_le16(body + 2);
        if (!query_span_ok(start, n))
            return make_exception(cfg, func, start, MB_EXC_ILLEGAL_ADDRESS, resp);

        /* header: addr func SN startLo startHi nBytes */
        resp[OFF_ADDR] = cfg->address;
        resp[OFF_FUNC] = func;
        memcpy(resp + OFF_SN, cfg->sn, MB_SN_LEN);
        wr_le16(resp + OFF_BODY, start);
        resp[OFF_BODY + 2] = (uint8_t)(n * 2);
        uint8_t *vp = resp + OFF_BODY + 3;

        for (uint16_t i = 0; i < n; i++) {
            uint16_t v = 0;
            mb_exception_t e = (func == MB_FC_READ_INPUT)
                ? cfg->regs.read_input(cfg->regs.ctx, (uint16_t)(start + i), &v)
                : cfg->regs.read_holding(cfg->regs.ctx, (uint16_t)(start + i), &v);
            if (e != MB_OK) return make_exception(cfg, func, start, e, resp);
            wr_le16(vp, v); vp += 2;
        }
        return finish(resp, (size_t)(vp - resp));
    }

    case MB_FC_WRITE_SINGLE: {  /* 0x06 */
        if (body_len < 4) return make_exception(cfg, func, 0, MB_EXC_ILLEGAL_VALUE, resp);
        uint16_t reg = rd_le16(body);
        uint16_t val = rd_le16(body + 2);
        mb_exception_t e = cfg->regs.write_holding(cfg->regs.ctx, reg, val);
        if (e != MB_OK) return make_exception(cfg, func, reg, e, resp);
        /* echo the request body back */
        resp[OFF_ADDR] = cfg->address;
        resp[OFF_FUNC] = func;
        memcpy(resp + OFF_SN, cfg->sn, MB_SN_LEN);
        wr_le16(resp + OFF_BODY, reg);
        wr_le16(resp + OFF_BODY + 2, val);
        return finish(resp, OFF_BODY + 4);
    }

    case MB_FC_WRITE_MULTI: {   /* 0x10 — spec: only SN and time setting */
        if (body_len < 5) return make_exception(cfg, func, 0, MB_EXC_ILLEGAL_VALUE, resp);
        uint16_t start = rd_le16(body);
        uint16_t n     = rd_le16(body + 2);
        uint8_t  nb    = body[4];
        if (n == 0 || n > MB_MAX_REGS_PER_QUERY || nb != n * 2 || body_len < (size_t)(5 + nb))
            return make_exception(cfg, func, start, MB_EXC_ILLEGAL_VALUE, resp);
        const uint8_t *vp = body + 5;
        for (uint16_t i = 0; i < n; i++) {
            mb_exception_t e = cfg->regs.write_holding(cfg->regs.ctx,
                                   (uint16_t)(start + i), rd_le16(vp));
            if (e != MB_OK) return make_exception(cfg, func, start, e, resp);
            vp += 2;
        }
        resp[OFF_ADDR] = cfg->address;
        resp[OFF_FUNC] = func;
        memcpy(resp + OFF_SN, cfg->sn, MB_SN_LEN);
        wr_le16(resp + OFF_BODY, start);
        wr_le16(resp + OFF_BODY + 2, n);
        return finish(resp, OFF_BODY + 4);
    }

    default:
        return make_exception(cfg, func, 0, MB_EXC_ILLEGAL_FUNCTION, resp);
    }
}
