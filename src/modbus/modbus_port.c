/*
 * Modbus-RTU port over the interrupt-driven USART3 driver (inv/uart.h).
 *
 * This is the hardware glue around the transport-agnostic engine in modbus.c.
 * Bytes are received in the USART3 ISR into a ring; this layer drains that ring
 * each poll, reassembles RTU frames by the inter-character gap, and queues any
 * response for background (interrupt) transmission — matching the factory, whose
 * USART3 Modbus is fully interrupt-driven (never polled from the main loop).
 *
 * CONFIRMED by RE (docs/05, docs/08): EG4 Modbus-family protocol on USART3,
 * address 0/1, funcs 0x03/0x04/0x06/0x10 plus undocumented 0x21/0x22/0x23;
 * USART3 is the only NVIC-vectored UART in the stock image.
 * RS-485 DE/RE: provide uart3_set_de() in a board file (the driver drives it).
 */
#include "inv/modbus.h"
#include "inv/uart.h"

#define MB_BAUD      19200U
#define MB_GAP_MS    2U          /* RTU inter-frame idle (~2 ms @ 19200) */

static uint8_t   rx_buf[MB_FRAME_MAX + 8];
static uint16_t  rx_len;
static uint32_t  last_byte_ms;
static const mb_config_t *s_cfg;

void mb_port_init(const mb_config_t *cfg)
{
    s_cfg = cfg;
    rx_len = 0;
    uart3_init(MB_BAUD);
}

/*
 * Call frequently from the main loop with a millisecond time base. Drains the
 * UART RX ring, and when the RTU inter-frame gap elapses, processes the
 * accumulated frame and queues any response for interrupt-driven transmit.
 */
void mb_port_poll(uint32_t now_ms)
{
    uint8_t b;
    while (uart3_rx_get(&b)) {
        if (rx_len < sizeof rx_buf) rx_buf[rx_len++] = b;
        last_byte_ms = now_ms;
    }

    if (rx_len > 0 && (uint32_t)(now_ms - last_byte_ms) >= MB_GAP_MS) {
        uint8_t resp[MB_FRAME_MAX];
        size_t n = inv_modbus_process(s_cfg, rx_buf, rx_len, resp, sizeof resp);
        rx_len = 0;
        if (n > 0) uart3_tx(resp, (uint32_t)n);
    }
}
