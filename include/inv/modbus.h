/*
 * Modbus-RTU slave engine (EG4/Luxpower variant) — public API.
 *
 * This is the TRANSPORT-AGNOSTIC protocol core: it turns a received request
 * frame into a response frame in caller-provided buffers. The UART/RS-485
 * plumbing (byte RX with inter-frame timeout, DE direction pin) lives in the
 * port layer (src/modbus/modbus_port.c) so this core can be unit-tested on a
 * host with no hardware. See docs/04-modbus.md and include/inv/modbus_map.h.
 *
 * Framing (per the EG4 18kPV-12LV protocol, shared by the 12000XP):
 *   request  read  (0x03/0x04): addr func SN[10] startLo startHi numLo numHi CRClo CRChi
 *   response read            :  addr func SN[10] startLo startHi nBytes [vLo vHi]*N CRClo CRChi
 *   request  write1 (0x06)    :  addr func SN[10] aLo aHi vLo vHi CRClo CRChi      (echoed back)
 *   request  writeN (0x10)    :  addr func SN[10] startLo startHi numLo numHi nBytes [vLo vHi]*N CRC
 *   response writeN           :  addr func SN[10] startLo startHi numLo numHi CRClo CRChi
 *   error                     :  addr (func|0x80) SN[10] startLo startHi excCode CRClo CRChi
 * Multi-byte fields are little-endian on the wire; CRC is Modbus CRC-16, lo then hi.
 */
#ifndef INV_MODBUS_H
#define INV_MODBUS_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* Modbus exception codes (Table 3). MB_OK means success. */
typedef enum {
    MB_OK                   = 0x00,
    MB_EXC_ILLEGAL_FUNCTION = 0x01,
    MB_EXC_ILLEGAL_ADDRESS  = 0x02,
    MB_EXC_ILLEGAL_VALUE    = 0x03,
    MB_EXC_SLAVE_FAILURE    = 0x04,
    MB_EXC_SLAVE_BUSY       = 0x06
} mb_exception_t;

/* Application register access. Each returns MB_OK or an exception code. */
typedef struct {
    mb_exception_t (*read_input)  (void *ctx, uint16_t addr, uint16_t *out);
    mb_exception_t (*read_holding)(void *ctx, uint16_t addr, uint16_t *out);
    mb_exception_t (*write_holding)(void *ctx, uint16_t addr, uint16_t val);
    void *ctx;
} mb_regmap_t;

typedef struct {
    uint8_t     address;      /* this device's bus address (Com Addr, holding reg 15) */
    uint8_t     sn[10];       /* device serial number (ASCII) echoed in responses      */
    bool        check_sn;     /* if true, ignore requests whose SN != ours             */
    mb_regmap_t regs;
} mb_config_t;

#define MB_SN_LEN             10
#define MB_MAX_REGS_PER_QUERY 40
#define MB_ADDR_BROADCAST     0

/* Largest frame we ever build: header(2)+SN(10)+start(2)+nBytes(1)+40*2+CRC(2) */
#define MB_FRAME_MAX          (2 + MB_SN_LEN + 2 + 1 + MB_MAX_REGS_PER_QUERY*2 + 2)

/*
 * Process one request frame and build the response.
 * Returns the response length written to `resp`, or 0 when no response should
 * be sent (bad CRC, wrong address, SN mismatch, or truncated frame).
 * `resp` must have capacity >= MB_FRAME_MAX.
 */
size_t inv_modbus_process(const mb_config_t *cfg,
                          const uint8_t *req, size_t req_len,
                          uint8_t *resp, size_t resp_cap);

/* Modbus CRC-16 (poly 0xA001, init 0xFFFF). Exposed for the port/tests. */
uint16_t inv_modbus_crc16(const uint8_t *buf, size_t len);

/* ---- UART/RS-485 port (src/modbus/modbus_port.c) ---- */
void mb_port_init(const mb_config_t *cfg);   /* configure USART3 @ 19200 8N1 */
void mb_port_poll(uint32_t now_ms);          /* call often with a ms time base */
void mb_port_set_tx(int tx);                 /* weak; override for RS-485 DE pin */

#endif /* INV_MODBUS_H */
