/*
 * DSP-link transmit port. Per the RE, the ARM<->DSP link is USART3 (<-> DSP
 * SCI-B). Polled byte TX of a pre-built frame.
 *
 * NOTE(port reconciliation): the stock firmware uses USART3 for the DSP link;
 * the external RS-485 *dongle* Modbus is a different UART. Our src/modbus/
 * port currently also targets USART3 as a placeholder — once the schematic
 * pins the dongle UART, move the Modbus slave there and leave USART3 to the DSP.
 */
#include "stm32f103.h"
#include "inv/dsp_link.h"

__attribute__((weak)) void dsp_link_tx(const uint8_t *frame, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        while (!(USART3->SR & USART_SR_TXE)) { }
        USART3->DR = frame[i];
    }
    while (!(USART3->SR & (1U << 6))) { }   /* wait TC */
}
