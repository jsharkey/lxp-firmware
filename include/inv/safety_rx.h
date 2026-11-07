/*
 * USART2 safety-CPU receiver: wire frame -> telemetry bank (docs/33, docs/39 T05).
 *
 * The redundant / "safety" CPU streams an EG4 "type-1", big-endian, CRC-16/MODBUS
 * frame to the ARM over USART2 (RXNE-interrupt-driven, not DMA -- docs/19 T02).
 * This is the parse half: a byte-stream state machine that assembles one frame,
 * checks its CRC, and distributes the fields into the telemetry bank
 * (`inv/safety_cpu.h` layout) and the operating mode / relayed fault+warn words.
 * The serve half (bank -> scaled Modbus input register) is `safety_cpu_publish()`.
 *
 * Frame layout (docs/33 §1):
 *   [0]      = 0x49           SOF
 *   [1]      = 0x01           type (gated)
 *   [2]      = seq/flags      (unused by the decode)
 *   [3]      = len            total frame = len + 6 bytes (assembler caps < 0x40)
 *   [4..N-3] = payload        header fields at fixed offsets + one tag sub-record
 *   [N-2..]  = CRC-16/MODBUS  over [0..N-3], big-endian (MSB first)
 *
 * Header fields (fixed offsets, every valid frame):
 *   [+4]  -> mode (u8)             [+0d] -> bank+0x01 (u8)
 *   [+5]  -> relayed fault (BE32)  [+0f] -> bank+0xc4 (BE16)
 *   [+9]  -> relayed warn  (BE32)  [+11],[+12] -> bank+0xca (lo,hi)   [+13] -> bank+0xe0
 * One tag sub-record follows at [+0x14] (selector), carrying the measurements
 * (grid/PV/bus voltages, frequencies, temps); the per-tag frame->bank map is in
 * docs/33 §1a. Unknown tags leave the measurement block untouched but the frame is
 * still accepted.
 *
 * The parser is pure and host-testable (tests/test_safety_rx.c). The hardware glue
 * (USART2 RXNE driver + poll) is src/safety/safety_rx_port.c.
 */
#ifndef INV_SAFETY_RX_H
#define INV_SAFETY_RX_H

#include <stdint.h>
#include "inv/safety_cpu.h"      /* SAFETY_BANK_SIZE, bank layout */

#define SAFETY_RX_SOF      0x49u
#define SAFETY_RX_TYPE1    0x01u
#define SAFETY_RX_MAXLEN   0x40u   /* assembler cap: total frame < 64 bytes (docs/33) */

typedef enum {
    SAFETY_RX_NONE = 0,   /* byte consumed; frame still assembling or discarded */
    SAFETY_RX_FRAME,      /* a complete, CRC-valid type-1 frame was decoded      */
    SAFETY_RX_BADCRC,     /* a complete frame failed CRC (dropped)               */
    SAFETY_RX_BADTYPE,    /* a complete frame had a non-type-1 byte (dropped)    */
} inv_safety_rx_evt_t;

typedef struct {
    uint8_t  *bank;           /* SAFETY_BANK_SIZE, docs/33 layout (decode target) */
    uint8_t   buf[SAFETY_RX_MAXLEN];
    uint16_t  idx;            /* bytes collected into buf                         */
    uint16_t  expected;       /* total frame length once the len byte is seen     */

    /* Latest decoded header (valid after SAFETY_RX_FRAME). These feed the state
     * classifier (inv_classify): mode byte + relayed fault/warn words. */
    uint8_t   mode;
    uint32_t  fault;
    uint32_t  warn;

    /* Diagnostics. */
    uint32_t  frames_ok;
    uint32_t  frames_badcrc;
    uint32_t  frames_badtype;
} inv_safety_rx_t;

/* Initialise the parser to write decoded telemetry into `bank`
 * (SAFETY_BANK_SIZE bytes). `bank` may be NULL for a header-only decode. */
void inv_safety_rx_init(inv_safety_rx_t *st, uint8_t *bank);

/* Feed one received byte. Returns SAFETY_RX_FRAME when a complete valid frame has
 * just been decoded into the bank (and st->mode/fault/warn updated); otherwise
 * SAFETY_RX_NONE / _BADCRC / _BADTYPE. Resynchronises automatically past a bad
 * SOF, a bad length, a failed CRC, or arbitrary garbage. */
inv_safety_rx_evt_t inv_safety_rx_byte(inv_safety_rx_t *st, uint8_t b);

/* Convenience: feed a buffer of bytes; returns the number of complete valid frames
 * decoded during the call. */
uint32_t inv_safety_rx_feed(inv_safety_rx_t *st, const uint8_t *buf, uint32_t len);

#endif /* INV_SAFETY_RX_H */
