/*
 * Interrupt-driven UART5 — the external RS-485 "dongle" Modbus port.
 * See include/inv/uart5.h. Mirrors src/uart/uart3.c; the only differences are
 * the peripheral (UART5, IRQ 53), its pins (PC12 TX / PD2 RX), and the RS-485
 * DE pin (PA15). The ARM is the Modbus slave on this bus (docs/26).
 */
#include "stm32f103.h"
#include "inv/uart5.h"
#include "inv/ringbuf.h"

#define UART5_RX_SIZE 256U      /* power of two; holds SIZE-1 bytes */
#define UART5_TX_SIZE 256U

static uint8_t   rx_store[UART5_RX_SIZE];
static uint8_t   tx_store[UART5_TX_SIZE];
static ringbuf_t rx_ring;
static ringbuf_t tx_ring;
static volatile uint8_t tx_active;      /* a transmit is in progress */

/*
 * RS-485 driver-enable on PA15 (the factory's inferred DE pin for this bus,
 * docs/wiring/ARM-UART5-dongle). PA15 is JTDI at reset, so freeing it needs the
 * SWJ remap (JTAG off, SW-DP kept). Weak so a board file can override.
 *
 * NB(real-HW): AFIO->MAPR SWJ_CFG reads as 0, so any later read-modify-write of
 * MAPR (e.g. the CAN remap) must re-assert SWJ_NOJTAG or it re-enables JTAG and
 * reclaims PA15. In this build the CAN remap is set before UART5 init; a board
 * file that reprograms MAPR afterwards must preserve SWJ_NOJTAG.
 */
__attribute__((weak)) void uart5_set_de(int tx_enable)
{
    if (tx_enable) GPIOA->BSRR = (1U << 15);    /* PA15 high: drive the bus */
    else           GPIOA->BRR  = (1U << 15);    /* PA15 low:  receive */
}

void uart5_init(uint32_t baud)
{
    rb_init(&rx_ring, rx_store, UART5_RX_SIZE);
    rb_init(&tx_ring, tx_store, UART5_TX_SIZE);
    tx_active = 0;

    RCC->APB1ENR |= RCC_APB1ENR_UART5EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPCEN |
                    RCC_APB2ENR_IOPDEN | RCC_APB2ENR_AFIOEN;

    /* Free PA15 from JTAG (keep SW-DP), then PA15 = push-pull output 50 MHz (DE) */
    AFIO->MAPR = (AFIO->MAPR & ~(7UL << 24)) | AFIO_MAPR_SWJ_NOJTAG;
    GPIOA->CRH = (GPIOA->CRH & ~0xF0000000U) | 0x30000000U;

    /* PC12 = UART5_TX (AF push-pull 50 MHz = 0xB) */
    GPIOC->CRH = (GPIOC->CRH & ~0x000F0000U) | 0x000B0000U;
    /* PD2  = UART5_RX (floating input = 0x4) */
    GPIOD->CRL = (GPIOD->CRL & ~0x00000F00U) | 0x00000400U;

    /* APB1 = SYSCLK/2 = 36 MHz */
    UART5->BRR = (SystemCoreClock / 2U) / baud;
    UART5->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE;

    uart5_set_de(0);                    /* receive mode */
    nvic_enable_irq(UART5_IRQn);
}

bool     uart5_rx_get(uint8_t *out) { return rb_get(&rx_ring, out); }
uint32_t uart5_rx_count(void)       { return rb_count(&rx_ring); }
bool     uart5_tx_idle(void)        { return !tx_active && rb_is_empty(&tx_ring); }

uint32_t uart5_tx(const uint8_t *buf, uint32_t len)
{
    uint32_t n = 0;
    for (; n < len; n++) {
        if (!rb_put(&tx_ring, buf[n])) break;   /* ring full: caller retries later */
    }
    if (n && !tx_active) {
        tx_active = 1;
        uart5_set_de(1);                        /* drive the bus before first byte */
        UART5->CR1 |= USART_CR1_TXEIE;          /* kick: TXE fires immediately */
    }
    return n;
}

void UART5_IRQHandler(void)
{
    /* RX: drain every available byte (reading DR clears RXNE), keeping a burst
     * together as one RTU frame. Drop on overflow. */
    while (UART5->SR & USART_SR_RXNE) {
        uint8_t b = (uint8_t)UART5->DR;
        (void)rb_put(&rx_ring, b);
    }

    /* TX: shift queued bytes out while the data register is empty. */
    if (UART5->CR1 & USART_CR1_TXEIE) {
        uint8_t b;
        while ((UART5->SR & USART_SR_TXE) && rb_get(&tx_ring, &b)) {
            UART5->DR = b;
        }
        if (rb_is_empty(&tx_ring)) {
            /* nothing left: stop TXE, wait for the last byte to fully leave the
             * shift register (TC) before releasing the RS-485 driver. */
            UART5->CR1 &= ~USART_CR1_TXEIE;
            UART5->CR1 |= USART_CR1_TCIE;
        }
    }

    /* TC: final byte has left the wire — hand the bus back to receive. */
    if ((UART5->SR & USART_SR_TC) && (UART5->CR1 & USART_CR1_TCIE)) {
        UART5->CR1 &= ~USART_CR1_TCIE;
        UART5->SR &= ~USART_SR_TC;              /* clear TC (rc_w0) */
        tx_active = 0;
        uart5_set_de(0);
    }
}
