/*
 * Interrupt-driven USART2 — the safety-CPU telemetry link. See include/inv/uart2.h.
 *
 * Receive side only (T05: the safety CPU streams telemetry to the ARM). RXNEIE is
 * always on and the ISR drains every available byte into a ring — matching the
 * factory, whose USART2 RX is interrupt-driven, not DMA (docs/19 T02). Pins PA2/PA3,
 * RS-485 direction on PC2 (docs/16), held in receive.
 */
#include "stm32f103.h"
#include "inv/uart2.h"
#include "inv/ringbuf.h"

#define UART2_RX_SIZE 256U      /* power of two; holds SIZE-1 bytes */

static uint8_t   rx_store[UART2_RX_SIZE];
static ringbuf_t rx_ring;

/* Weak RS-485 DE/RE hook (PC2) — a board file provides the real one. */
__attribute__((weak)) void uart2_set_de(int tx_enable) { (void)tx_enable; }

void uart2_init(uint32_t baud)
{
    rb_init(&rx_ring, rx_store, UART2_RX_SIZE);

    RCC->APB1ENR |= RCC_APB1ENR_USART2EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
    /* PA2 = TX (AF push-pull 50 MHz = 0xB), PA3 = RX (floating input = 0x4).
     * Pins 2,3 occupy CRL nibbles [11:8] and [15:12]. */
    GPIOA->CRL = (GPIOA->CRL & ~0x0000FF00U) | 0x00004B00U;

    /* APB1 = SYSCLK/2 = 36 MHz */
    USART2->BRR = (SystemCoreClock / 2U) / baud;
    USART2->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE;

    uart2_set_de(0);                    /* receive mode */
    nvic_enable_irq(USART2_IRQn);
}

bool     uart2_rx_get(uint8_t *out) { return rb_get(&rx_ring, out); }
uint32_t uart2_rx_count(void)       { return rb_count(&rx_ring); }

void USART2_IRQHandler(void)
{
    /* Drain every byte currently available (reading DR clears RXNE); draining in a
     * loop keeps a frame burst together rather than spreading it across poll ticks.
     * Drop silently on ring overflow. */
    while (USART2->SR & USART_SR_RXNE) {
        uint8_t b = (uint8_t)USART2->DR;
        (void)rb_put(&rx_ring, b);
    }
}
