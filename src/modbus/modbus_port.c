/*
 * Modbus-RTU port over the interrupt-driven UART5 driver (inv/uart5.h) — the
 * external RS-485 "dongle" link.
 *
 * This is the hardware glue around the transport-agnostic engine in modbus.c.
 * Bytes are received in the UART5 ISR into a ring; this layer drains that ring
 * each poll, reassembles RTU frames by the inter-character gap, and queues any
 * response for background (interrupt) transmission.
 *
 * Port (docs/26, docs/wiring/ARM-UART5-dongle): the factory serves the plug-in
 * datalogger on **UART5** (PC12 TX / PD2 RX, RS-485 half-duplex, DE on PA15),
 * where the ARM is the Modbus *slave* — not USART3, which is the ARM↔DSP link
 * (the ARM is the master there, so a dongle master cannot sit on it). The UART5
 * driver drives the RS-485 DE (PA15) around each transmit via uart5_set_de().
 *
 * Framing (EG4 Modbus-family): address 0/1, funcs 0x03/0x04/0x06/0x10 plus the
 * bootloader 0x21/0x22/0x23. Baud: the spec says 19200; this image's UART5 reads
 * 9600 and the dongle baud is field-configurable (docs/wiring/ARM-UART5-dongle).
 */
#include "inv/modbus.h"
#include "inv/uart5.h"

#define MB_BAUD      9600U
#define MB_GAP_MS    4U          /* RTU inter-frame idle (~4 ms @ 9600) */

static uint8_t   rx_buf[MB_FRAME_MAX + 8];
static uint16_t  rx_len;
static uint32_t  last_byte_ms;
static const mb_config_t *s_cfg;

void mb_port_init(const mb_config_t *cfg)
{
    s_cfg = cfg;
    rx_len = 0;
    uart5_init(MB_BAUD);
}

/*
 * Call frequently from the main loop with a millisecond time base. Drains the
 * UART RX ring, and when the RTU inter-frame gap elapses, processes the
 * accumulated frame and queues any response for interrupt-driven transmit.
 */
void mb_port_poll(uint32_t now_ms)
{
    uint8_t b;
    while (uart5_rx_get(&b)) {
        if (rx_len < sizeof rx_buf) rx_buf[rx_len++] = b;
        last_byte_ms = now_ms;
    }

    if (rx_len > 0 && (uint32_t)(now_ms - last_byte_ms) >= MB_GAP_MS) {
        uint8_t resp[MB_FRAME_MAX];
        size_t n = inv_modbus_process(s_cfg, rx_buf, rx_len, resp, sizeof resp);
        rx_len = 0;
        if (n > 0) uart5_tx(resp, (uint32_t)n);
    }
}
