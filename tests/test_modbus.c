/*
 * Host unit tests for the Modbus-RTU slave engine. Build & run:  make test
 * No hardware needed — exercises the transport-agnostic core.
 */
#include "inv/modbus.h"
#include "inv/modbus_map.h"
#include "inv/states.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0, g_run = 0;
#define EXC_OFF 14   /* addr+func+SN[10]+start[2] -> exception code byte */
#define CHECK(cond, msg) do { g_run++; if (!(cond)) { \
    printf("  FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__); g_fail++; } } while (0)

/* ---- a trivial register model ---- */
static uint16_t input_regs[160];
static uint16_t holding_regs[256];

static mb_exception_t rd_in(void *c, uint16_t a, uint16_t *o) {
    (void)c;
    if (a >= 160) return MB_EXC_ILLEGAL_ADDRESS;
    *o = input_regs[a];
    return MB_OK;
}
static mb_exception_t rd_hold(void *c, uint16_t a, uint16_t *o) {
    (void)c;
    if (a >= 256) return MB_EXC_ILLEGAL_ADDRESS;
    *o = holding_regs[a];
    return MB_OK;
}
static mb_exception_t wr_hold(void *c, uint16_t a, uint16_t v) {
    (void)c;
    if (a >= 256) return MB_EXC_ILLEGAL_ADDRESS;
    holding_regs[a] = v;
    return MB_OK;
}

static const uint8_t SN[10] = {'A','B','1','2','3','4','5','6','7','8'};
static mb_config_t cfg = {
    .address = 1, .check_sn = false,
    .sn = {'A','B','1','2','3','4','5','6','7','8'},
    .regs = { rd_in, rd_hold, wr_hold, NULL }
};

/* build a request: addr func SN[10] <body...> CRC(lo,hi). returns length. */
static size_t build(uint8_t *f, uint8_t addr, uint8_t func,
                    const uint8_t *body, size_t blen)
{
    size_t n = 0;
    f[n++] = addr; f[n++] = func;
    memcpy(f + n, SN, 10); n += 10;
    memcpy(f + n, body, blen); n += blen;
    uint16_t crc = inv_modbus_crc16(f, n);
    f[n++] = (uint8_t)crc; f[n++] = (uint8_t)(crc >> 8);
    return n;
}

int main(void)
{
    uint8_t req[128], resp[MB_FRAME_MAX];
    size_t rl, n;

    /* 1. CRC-16/Modbus known vector: "123456789" -> 0x4B37 */
    CHECK(inv_modbus_crc16((const uint8_t*)"123456789", 9) == 0x4B37, "crc16 known vector");

    /* 2. Read input reg 0 (State), n=1 */
    input_regs[IR_STATE] = STATE_PV_BAT_OFFGRID; /* 0xC0 */
    { uint8_t b[] = { IR_STATE & 0xFF, IR_STATE >> 8, 1, 0 };
      rl = build(req, 1, MB_FC_READ_INPUT, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(n == 2+10+2+1+2+2, "read1 response length");
      CHECK(resp[0]==1 && resp[1]==MB_FC_READ_INPUT, "read1 addr+func");
      CHECK(memcmp(resp+2, SN, 10)==0, "read1 echoes SN");
      CHECK(resp[12]==(IR_STATE&0xFF) && resp[13]==(IR_STATE>>8), "read1 echoes start");
      CHECK(resp[14]==2, "read1 byte count");
      CHECK((resp[15] | (resp[16]<<8)) == STATE_PV_BAT_OFFGRID, "read1 value");
      CHECK(inv_modbus_crc16(resp, n-2) == (uint16_t)(resp[n-2]|(resp[n-1]<<8)), "read1 crc ok");
    }

    /* 3. Read input, 4 regs starting at 12 (VacR..Fac) */
    input_regs[12]=2400; input_regs[13]=2401; input_regs[14]=0; input_regs[15]=6000;
    { uint8_t b[] = { 12, 0, 4, 0 };
      rl = build(req, 1, MB_FC_READ_INPUT, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(resp[14]==8, "read4 byte count");
      CHECK((resp[15]|(resp[16]<<8))==2400 && (resp[21]|(resp[22]<<8))==6000, "read4 values");
    }

    /* 4. Bad CRC -> no response */
    { uint8_t b[] = { 0,0,1,0 };
      rl = build(req, 1, MB_FC_READ_INPUT, b, sizeof b);
      req[rl-1] ^= 0xFF;                      /* corrupt CRC */
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(n == 0, "bad crc -> no response");
    }

    /* 5. Wrong address -> no response */
    { uint8_t b[] = { 0,0,1,0 };
      rl = build(req, 9, MB_FC_READ_INPUT, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(n == 0, "wrong address -> no response");
    }

    /* 6. Write single holding reg 15 (Com Addr) = 2 */
    { uint8_t b[] = { HR_COM_ADDR & 0xFF, HR_COM_ADDR >> 8, 2, 0 };
      rl = build(req, 1, MB_FC_WRITE_SINGLE, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(holding_regs[HR_COM_ADDR]==2, "write1 updated model");
      CHECK(n==2+10+4+2 && resp[1]==MB_FC_WRITE_SINGLE, "write1 echo");
      CHECK((resp[14]|(resp[15]<<8))==2, "write1 echo value");
    }

    /* 7. Group-boundary crossing (start 38, n 5 crosses 40) -> exception 0x02 */
    { uint8_t b[] = { 38, 0, 5, 0 };
      rl = build(req, 1, MB_FC_READ_INPUT, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(resp[1]==(MB_FC_READ_INPUT|0x80), "span exception func");
      CHECK(resp[EXC_OFF]==MB_EXC_ILLEGAL_ADDRESS, "span exception code");
    }

    /* 8. Illegal function 0x07 -> exception 0x01 */
    { uint8_t b[] = { 0,0 };
      rl = build(req, 1, 0x07, b, sizeof b);
      n = inv_modbus_process(&cfg, req, rl, resp, sizeof resp);
      CHECK(resp[1]==(0x07|0x80), "illegal func -> 0x87");
      CHECK(resp[EXC_OFF]==MB_EXC_ILLEGAL_FUNCTION, "illegal func code");
    }

    printf("%s: %d/%d checks passed\n", g_fail?"FAILED":"OK", g_run-g_fail, g_run);
    return g_fail ? 1 : 0;
}
