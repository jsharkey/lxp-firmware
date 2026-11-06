/*
 * USART3 (ARM<->DSP link) receive-side demux — T09 finding.
 *
 * The roadmap expected the ARM to parse the DSP's `0x49` type-1 telemetry frame
 * on USART3. It does NOT. Reverse-engineering the factory USART3 RX byte handler
 * (ISR 0x0801c775 -> sub_0801c3e6, assembling into RAM 0x20007490) shows the ARM
 * treats USART3 RX as:
 *   - a **Modbus slave** request: byte[0] == our device address (or 0 = broadcast),
 *     byte[1] in {0x03, 0x04, 0x06, 0x10}; and
 *   - a **DSP firmware-update bootloader** frame: byte[1] in {0x21, 0x22, 0x23}.
 * Any other second byte -- including 0x01, the type of a `SOF 0x49` telemetry
 * frame -- resets the assembler, so a `0x49` frame never assembles (a `0x49` first
 * byte also fails the address match and is dropped at index 0).
 *
 * So the DSP-direct `0x49` telemetry is not consumed by the ARM; the ARM's
 * authoritative state / faults / measurements come from the safety CPU's `0x49`
 * frame on **USART2** (bank 0x20009e54, parser sub_080259d8; docs/22, docs/33).
 * The earlier telemetry-0x49 doc mis-attributed that USART2 bank parser to
 * USART3. This classifier mirrors the factory's USART3 RX framing decision so our
 * firmware encodes the same understanding (and never mistakes `0x49` for telemetry).
 */
#ifndef INV_DSP_RX_H
#define INV_DSP_RX_H

#include <stdint.h>
#include "inv/modbus.h"     /* mb_config_t, for the RX service below */

typedef enum {
    DSP_RX_REJECT = 0,     /* not a frame the ARM accepts on USART3 (e.g. 0x49) */
    DSP_RX_MODBUS,         /* a Modbus request (func 03/04/06/10), ARM as slave  */
    DSP_RX_BOOTLOADER,     /* a DSP firmware-update frame (func 21/22/23)        */
} dsp_rx_class_t;

/* Classify a USART3 RX frame from its first two bytes, as the factory does:
 * `first` must equal `dev_addr` (or 0 = broadcast), and `func` selects the class.
 * Returns DSP_RX_REJECT for anything else (notably a 0x49/type-1 telemetry frame). */
dsp_rx_class_t inv_dsp_rx_classify(uint8_t first, uint8_t func, uint8_t dev_addr);

/* ---- USART3 RX demux service (src/dsp/dsp_rx_port.c) ----
 * The hardware/plumbing half of the finding above (the pure classifier is the
 * core, src/dsp/dsp_rx.c). Polled and cooperative: drain the USART3 receive
 * register, assemble one RTU frame per inter-frame idle gap, classify it with
 * inv_dsp_rx_classify() and route it --
 *   - DSP_RX_MODBUS:     serve it against `mb` as a slave and send the reply back
 *                        on USART3 (the DSP polls the ARM over this wire, exactly
 *                        as the factory answers register reads/writes here);
 *   - DSP_RX_BOOTLOADER: recognised for the DSP firmware-update path (T18);
 *   - DSP_RX_REJECT:     dropped unconsumed -- notably a 0x49 telemetry SOF.
 * Call often with a free-running millisecond time base; `mb` is the same register
 * map the dongle slave uses. */
void inv_dsp_rx_poll(const mb_config_t *mb, uint32_t now_ms);

#endif /* INV_DSP_RX_H */
