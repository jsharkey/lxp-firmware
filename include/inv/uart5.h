/*
 * Interrupt-driven UART5 driver — the external RS-485 "dongle" Modbus port.
 *
 * The factory serves the plug-in datalogger on UART5 (PC12 TX / PD2 RX,
 * RS-485 half-duplex, DE on PA15) — not USART3, which is the ARM↔DSP link
 * (docs/26, docs/wiring/ARM-UART5-dongle). The ARM is the Modbus *slave* on this
 * bus. This driver mirrors the uart3 one: RXNEIE always on, TXEIE only while a
 * transmit is in flight, TCIE once at end-of-transmit to release the DE line.
 */
#ifndef INV_UART5_H
#define INV_UART5_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Bring up UART5 at `baud` (8N1) with RX interrupt enabled, and PA15 as DE. */
void uart5_init(uint32_t baud);

/* RX: pull one received byte from the ring. Returns false when none pending. */
bool     uart5_rx_get(uint8_t *out);
uint32_t uart5_rx_count(void);

/* TX: queue `len` bytes; returns the number accepted (short if the ring fills).
 * Transmission proceeds in the background under interrupt. */
uint32_t uart5_tx(const uint8_t *buf, uint32_t len);
bool     uart5_tx_idle(void);          /* true once the TX ring has drained + TC */

/* RS-485 direction control (1 = transmit/drive, 0 = receive). The driver calls
 * it automatically: TX enabled before the first queued byte, RX restored on TC.
 * Weak default drives PA15; a board file may override for a different DE pin. */
void uart5_set_de(int tx_enable);

#endif /* INV_UART5_H */
