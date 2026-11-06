/*
 * ARM -> DSP configuration push (USART3 <-> DSP SCI-B) — public API.
 *
 * Implements the downlink documented in docs/08-arm-dsp-config-protocol.md:
 * the ARM is the master and continuously streams the COMPLETE set of 9 config
 * blocks (ids 0..8) as a repeating full snapshot — it does NOT send deltas; the
 * DSP diffs each received value against its stored copy and acts on changes
 * (see docs/07 for the AC-First / block-0 semantics it drives).
 *
 * Frame (bytes on the USART3 wire; the C28x DSP receives one byte per 16-bit
 * word at RAM 0x00AC80):
 *   [0x00]      address            (EG4 framing)
 *   [0x01]      type = 1           (selects the DSP settings deserialiser)
 *   [0x02..13]  18-byte header     SN[10] + aux (timestamp plausible; see docs/08)
 *   [0x14]      block id (0..7)    selects which block payload follows
 *   [0x15..]    block payload      positionally packed struct (per block)
 *   [len-2..]   CRC-16/Modbus      (reflected 0xA001; shared with the whole EG4 family)
 *
 * FIDELITY: the frame envelope, block-id scheme, CRC, cadence and "full snapshot"
 * behaviour are from RE of both ends and are reproduced faithfully. The exact
 * field order/width INSIDE each block payload is only partially recovered
 * (block 0 best-effort; 1..7 are target-RAM clusters, see docs/08). Those are
 * marked TODO and assembled from the register model via an editable field table,
 * so contributors can fill them in as they are decoded without touching the
 * framing/scheduler.
 */
#ifndef INV_DSP_LINK_H
#define INV_DSP_LINK_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define DSP_FRAME_TYPE_CONFIG   1
#define DSP_CONFIG_NBLOCKS      9   /* ids 0..8 (matches the factory deserialiser) */
#define DSP_SN_LEN              10

/* wire byte offsets */
#define DSP_OFF_ADDR            0x00
#define DSP_OFF_TYPE            0x01
#define DSP_OFF_HEADER          0x02    /* 18 bytes of SN+aux */
#define DSP_OFF_BLOCKID         0x14
#define DSP_OFF_PAYLOAD         0x15

#define DSP_FRAME_MAX           128     /* generous; real blocks are << this */

/* Everything the push needs from the rest of the system. The config values are
 * read from the same holding-register model the HMI/Modbus layers use, so an
 * HMI edit or a dongle write is picked up by the next snapshot automatically. */
typedef struct {
    uint8_t  address;                   /* DSP link address (framing)        */
    uint8_t  sn[DSP_SN_LEN];            /* device serial number              */
    /* current wall-clock (ARM is the timekeeper); pushed in the header       */
    uint8_t  year, month, day, hour, minute, second;
    /* read a holding register (HR_* in inv/modbus_map.h); false if unknown   */
    bool   (*read_holding)(void *ctx, uint16_t reg, uint16_t *out);
    void    *ctx;
} dsp_cfg_src_t;

/* Build the type-1 config frame for `block_id` (0..8) into `out`.
 * Returns the total frame length (incl. CRC), or 0 on error. */
size_t dsp_build_config_frame(const dsp_cfg_src_t *src, uint8_t block_id,
                              uint8_t *out, size_t cap);

/* Driver state: rotates through the 9 blocks, one per tick, forever. */
typedef struct { uint8_t next_block; } dsp_push_t;

static inline void dsp_push_init(dsp_push_t *p) { p->next_block = 0; }

/* Build the next block's frame and advance the rotation. Call periodically
 * (the stock firmware does so once per comms-task cycle). Returns frame length. */
size_t dsp_push_next(dsp_push_t *p, const dsp_cfg_src_t *src,
                     uint8_t *out, size_t cap);

/* CRC-16/Modbus (reflected 0xA001) — same routine as the Modbus layer and the
 * DSP's FUN_00081034 (docs/08). Declared here for tests. */
uint16_t dsp_crc16(const uint8_t *buf, size_t len);

/* ---- port (src/dsp/dsp_link_port.c): the ARM↔DSP link on USART3 ---- */
/* Configure USART3 for the DSP push (TX). Call once at boot: the dongle Modbus
 * now owns UART5 (docs/26), so USART3 is the DSP's alone and must be brought up
 * here rather than as a side effect of the Modbus port init. */
void dsp_link_port_init(uint32_t baud);
void dsp_link_tx(const uint8_t *frame, size_t len);

#endif /* INV_DSP_LINK_H */
