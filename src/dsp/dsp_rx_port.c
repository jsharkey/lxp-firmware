/*
 * USART3 (ARM<->DSP link) RX demux service -- the hardware/plumbing half of the
 * T09 finding. The pure framing decision is src/dsp/dsp_rx.c
 * (inv_dsp_rx_classify); this is the cooperative, polled port layer that feeds
 * it, mirroring the modbus.c / modbus_port.c core/port split.
 *
 * The ARM's real USART3 RX is an ISR byte handler (sub_0801c3e6) that assembles
 * a frame and demuxes it into a Modbus-slave request or a DSP bootloader frame;
 * a 0x49 telemetry SOF is rejected (see include/inv/dsp_rx.h and
 * docs/wiring/ARM-USART3-DSP/telemetry-0x49.md). We reproduce that decision from
 * the cooperative main loop: USART3 is brought up by dsp_link_port_init() (TX +
 * RX enabled), so here we just drain the receive register, delimit frames by the
 * inter-frame idle gap, and route each one through the classifier.
 */
#include "stm32f103.h"
#include "inv/dsp_rx.h"
#include "inv/dsp_link.h"   /* dsp_link_tx() to answer on USART3 */
#include "inv/modbus.h"

/* At 19200 8N1 one byte is ~0.52 ms and the RTU inter-frame gap (3.5 chars) is
 * ~1.8 ms; round up to 2 ms for the 1 ms loop time base. A frame is considered
 * complete once the line has been idle for this long. */
#define DSP_RX_IFG_MS   2U

static uint8_t  s_buf[MB_FRAME_MAX];   /* assembling frame (incl. CRC)        */
static uint16_t s_len;                 /* bytes buffered so far               */
static uint32_t s_last_ms;             /* arrival time of the last RX byte    */
static int      s_have_last;           /* s_last_ms valid (first byte seen)   */

static void dsp_rx_dispatch(const mb_config_t *mb, const uint8_t *f, uint16_t n)
{
    if (n < 2) return;                 /* too short to carry address + func */
    switch (inv_dsp_rx_classify(f[0], f[1], mb->address)) {
    case DSP_RX_MODBUS: {
        uint8_t resp[MB_FRAME_MAX];
        size_t rn = inv_modbus_process(mb, f, n, resp, sizeof resp);
        if (rn) dsp_link_tx(resp, rn);     /* answer the DSP on USART3 */
        break;
    }
    case DSP_RX_BOOTLOADER:
        /* DSP firmware-update channel (func 21/22/23): recognised; handled by
         * the bootloader path (T18). Nothing to do here yet. */
        break;
    case DSP_RX_REJECT:
    default:
        break;    /* not consumed on USART3 (e.g. a 0x49 telemetry SOF) */
    }
}

void inv_dsp_rx_poll(const mb_config_t *mb, uint32_t now_ms)
{
    /* A buffered frame with no new byte for the inter-frame gap is complete. */
    if (s_len && s_have_last && (uint32_t)(now_ms - s_last_ms) >= DSP_RX_IFG_MS) {
        dsp_rx_dispatch(mb, s_buf, s_len);
        s_len = 0;
    }
    /* Drain everything received since the last pass (reading DR clears RXNE). */
    while (USART3->SR & USART_SR_RXNE) {
        uint8_t b = (uint8_t)USART3->DR;
        if (s_have_last && (uint32_t)(now_ms - s_last_ms) >= DSP_RX_IFG_MS)
            s_len = 0;                     /* gap since the previous byte -> new frame */
        s_last_ms = now_ms;
        s_have_last = 1;
        if (s_len < sizeof s_buf)
            s_buf[s_len++] = b;            /* overflow: keep the head, drop the rest */
    }
}
