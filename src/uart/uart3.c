/*
 * Interrupt-driven USART3 — implementation. See include/inv/uart.h.
 *
 * Factory parity: the stock firmware's only vectored UART is USART3 (IRQ 39).
 * We do the same — RXNEIE always on, TXEIE enabled only while a transmit is in
 * flight, TCIE used once at end-of-transmit to release the RS-485 line. The ring
 * buffers (inv/ringbuf.h) make the ISR/thread hand-off lock-free.
 */
#include "stm32f103.h"
#include "inv/uart.h"
#include "inv/ringbuf.h"

#define UART3_RX_SIZE 256U      /* power of two; holds SIZE-1 bytes */
#define UART3_TX_SIZE 256U

static uint8_t   rx_store[UART3_RX_SIZE];
static uint8_t   tx_store[UART3_TX_SIZE];
static ringbuf_t rx_ring;
static ringbuf_t tx_ring;
static volatile uint8_t tx_active;      /* a transmit is in progress */

/* Weak RS-485 DE/RE hook — a board file provides the real one. */
__attribute__((weak)) void uart3_set_de(int tx_enable) { (void)tx_enable; }

void uart3_init(uint32_t baud)
{
    rb_init(&rx_ring, rx_store, UART3_RX_SIZE);
    rb_init(&tx_ring, tx_store, UART3_TX_SIZE);
    tx_active = 0;

    RCC->APB1ENR |= RCC_APB1ENR_USART3EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
    /* PB10 = TX (AF push-pull 50 MHz = 0xB), PB11 = RX (floating input = 0x4) */
    GPIOB->CRH = (GPIOB->CRH & ~0x0000FF00U) | 0x00004B00U;

    /* APB1 = SYSCLK/2 = 36 MHz */
    USART3->BRR = (SystemCoreClock / 2U) / baud;
    USART3->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE;

    uart3_set_de(0);                    /* receive mode */
    nvic_enable_irq(USART3_IRQn);
}

bool     uart3_rx_get(uint8_t *out) { return rb_get(&rx_ring, out); }
uint32_t uart3_rx_count(void)       { return rb_count(&rx_ring); }
bool     uart3_tx_idle(void)        { return !tx_active && rb_is_empty(&tx_ring); }

uint32_t uart3_tx(const uint8_t *buf, uint32_t len)
{
    uint32_t n = 0;
    for (; n < len; n++) {
        if (!rb_put(&tx_ring, buf[n])) break;   /* ring full: caller retries later */
    }
    if (n && !tx_active) {
        tx_active = 1;
        uart3_set_de(1);                        /* drive the bus before first byte */
        USART3->CR1 |= USART_CR1_TXEIE;         /* kick: TXE fires immediately */
    }
    return n;
}

void USART3_IRQHandler(void)
{
    uint32_t sr = USART3->SR;

    /* RX: a byte arrived. Reading DR clears RXNE. Drop on overflow rather than
     * stall the ISR — the RTU inter-frame gap resynchronises the frame. */
    if (sr & USART_SR_RXNE) {
        uint8_t b = (uint8_t)USART3->DR;
        (void)rb_put(&rx_ring, b);
    }

    /* TX: data register empty and we have more to send. */
    if ((sr & USART_SR_TXE) && (USART3->CR1 & USART_CR1_TXEIE)) {
        uint8_t b;
        if (rb_get(&tx_ring, &b)) {
            USART3->DR = b;
        } else {
            /* nothing left: stop TXE, wait for the last byte to fully leave the
             * shift register (TC) before releasing the RS-485 driver. */
            USART3->CR1 &= ~USART_CR1_TXEIE;
            USART3->CR1 |= USART_CR1_TCIE;
        }
    }

    /* TC: final byte has left the wire — hand the bus back to receive. */
    if ((sr & USART_SR_TC) && (USART3->CR1 & USART_CR1_TCIE)) {
        USART3->CR1 &= ~USART_CR1_TCIE;
        USART3->SR &= ~USART_SR_TC;             /* clear TC (rc_w0) */
        tx_active = 0;
        uart3_set_de(0);
    }
}
