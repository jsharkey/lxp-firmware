/*
 * DSP-link transmit port. Per the RE, the ARM<->DSP link is USART3 (<-> DSP
 * SCI-B). Polled byte TX of a pre-built frame.
 *
 * The external RS-485 *dongle* Modbus now lives on its own UART (UART5, docs/26,
 * docs/wiring/ARM-UART5-dongle), so USART3 is the DSP's alone. It is brought up
 * here (dsp_link_port_init) instead of relying on the Modbus port's init.
 */
#include "stm32f103.h"
#include "inv/dsp_link.h"

/* Configure USART3 for DSP TX (8N1, TX-only; we don't RX the DSP yet — T09). */
__attribute__((weak)) void dsp_link_port_init(uint32_t baud)
{
    RCC->APB1ENR |= RCC_APB1ENR_USART3EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;
    /* PB10 = USART3_TX (AF push-pull 50 MHz = 0xB), PB11 = USART3_RX (floating
     * input = 0x4) -- the DSP link is bidirectional (RX parsing is T09); set both
     * so the port matches the factory's USART3 bring-up. */
    GPIOB->CRH = (GPIOB->CRH & ~0x0000FF00U) | 0x00004B00U;
    USART3->BRR = (SystemCoreClock / 2U) / baud;   /* APB1 = SYSCLK/2 */
    USART3->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

__attribute__((weak)) void dsp_link_tx(const uint8_t *frame, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        while (!(USART3->SR & USART_SR_TXE)) { }
        USART3->DR = frame[i];
    }
    while (!(USART3->SR & (1U << 6))) { }   /* wait TC */
}
