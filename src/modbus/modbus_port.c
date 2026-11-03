/*
 * Modbus-RTU UART/RS-485 port for USART3 (the recovered USART3 IRQ is the one
 * real comms interrupt in the stock firmware). This is the hardware glue around
 * the transport-agnostic engine in modbus.c.
 *
 * TODO(schematic): confirm USART3 is the RS-485 Modbus port (vs the DSP link),
 * its pins (PB10/PB11 default), and the RS-485 driver-enable (DE/RE) GPIO.
 * Override mb_port_set_tx() for your board's DE pin.
 */
#include "stm32f103.h"
#include "inv/modbus.h"

#define MB_BAUD 19200U

static uint8_t   rx_buf[MB_FRAME_MAX + 8];
static uint16_t  rx_len;
static uint32_t  last_byte_ms;
static const mb_config_t *s_cfg;

/* RS-485 direction. Weak so a board file can drive the real DE/RE pin. */
__attribute__((weak)) void mb_port_set_tx(int tx) { (void)tx; }

void mb_port_init(const mb_config_t *cfg)
{
    s_cfg = cfg;
    rx_len = 0;

    /* clocks: USART3 (APB1) + GPIOB (APB2) */
    RCC->APB1ENR |= RCC_APB1ENR_USART3EN;
    RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;

    /* PB10 = TX (AF push-pull, 50MHz = 0xB), PB11 = RX (floating input = 0x4) */
    GPIOB->CRH = (GPIOB->CRH & ~0x0000FF00U) | 0x00004B00U;

    /* 19200 8N1 on PCLK1 (= SYSCLK/2 = 36 MHz) */
    USART3->BRR = (SystemCoreClock / 2U) / MB_BAUD;
    USART3->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;

    mb_port_set_tx(0);                   /* receive mode */
}

static void tx_frame(const uint8_t *buf, uint16_t len)
{
    mb_port_set_tx(1);
    for (uint16_t i = 0; i < len; i++) {
        while (!(USART3->SR & USART_SR_TXE)) { }
        USART3->DR = buf[i];
    }
    while (!(USART3->SR & (1U << 6))) { } /* wait TC (transmission complete) */
    mb_port_set_tx(0);
}

/*
 * Call frequently from the main loop with a millisecond time base. Drains the
 * UART, and when the RTU inter-frame gap (~2 ms @ 19200) elapses, processes the
 * accumulated frame and transmits any response.
 */
void mb_port_poll(uint32_t now_ms)
{
    while (USART3->SR & USART_SR_RXNE) {
        uint8_t b = (uint8_t)USART3->DR;
        if (rx_len < sizeof rx_buf) rx_buf[rx_len++] = b;
        last_byte_ms = now_ms;
    }

    if (rx_len > 0 && (uint32_t)(now_ms - last_byte_ms) >= 2U) {
        uint8_t resp[MB_FRAME_MAX];
        size_t n = inv_modbus_process(s_cfg, rx_buf, rx_len, resp, sizeof resp);
        rx_len = 0;
        if (n > 0) tx_frame(resp, (uint16_t)n);
    }
}
