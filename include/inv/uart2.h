/*
 * Interrupt-driven USART2 driver — the safety-CPU telemetry link (docs/16, docs/33).
 *
 * The redundant / "safety" CPU streams its EG4 type-1 frame to the ARM over USART2
 * (PA2 TX / PA3 RX, RS-485 direction on PC2 — docs/16). The factory receives it
 * RXNE-interrupt-driven, not by DMA (CR1 RXNEIE set, CR3 DMAR clear — docs/19 T02);
 * we match that. This is the receive side (the link is inbound telemetry for T05):
 * RX bytes land in a ring the main loop drains and hands to inv_safety_rx (the
 * parser). The ISR is USART2_IRQHandler (IRQ 38 / vector 54), the one the factory
 * uses for this link.
 */
#ifndef INV_UART2_H
#define INV_UART2_H

#include <stdint.h>
#include <stdbool.h>

/* Bring up USART2 at `baud` (8N1), RX interrupt enabled, direction pin in receive. */
void uart2_init(uint32_t baud);

/* Pull one received byte from the ring. Returns false when none pending. */
bool     uart2_rx_get(uint8_t *out);
uint32_t uart2_rx_count(void);

/* RS-485 direction control for the USART2 bus (PC2). Weak no-op default; a board
 * file overrides it (1 = drive/transmit, 0 = receive). Held in receive for T05. */
void uart2_set_de(int tx_enable);

#endif /* INV_UART2_H */
