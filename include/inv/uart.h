/*
 * Interrupt-driven USART3 driver (the DSP / RS-485 link).
 *
 * This mirrors the factory firmware, which services USART3 entirely from its
 * interrupt (vector 55 / IRQ 39 is the one real UART ISR in the stock image;
 * RXNEIE is set and bytes are taken in the handler, never polled — see the
 * docs/08 link analysis). RX bytes land in a ring the main loop drains; TX bytes
 * are queued and shifted out under TXE interrupt, with the RS-485 driver-enable
 * dropped after the final byte completes (TC).
 */
#ifndef INV_UART_H
#define INV_UART_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Bring up USART3 at `baud` (8N1) with RX interrupt enabled. */
void uart3_init(uint32_t baud);

/* RX: pull one received byte from the ring. Returns false when none pending. */
bool   uart3_rx_get(uint8_t *out);
uint32_t uart3_rx_count(void);

/* TX: queue `len` bytes; returns the number accepted (short if the ring fills).
 * Transmission proceeds in the background under interrupt. */
uint32_t uart3_tx(const uint8_t *buf, uint32_t len);
bool     uart3_tx_idle(void);          /* true once the TX ring has drained + TC */

/* RS-485 direction control. Weak default is a no-op; a board file overrides it
 * to drive the DE/RE pin (1 = transmit/drive, 0 = receive). The driver calls it
 * automatically: TX enabled before the first queued byte, RX restored on TC. */
void uart3_set_de(int tx_enable);

#endif /* INV_UART_H */
