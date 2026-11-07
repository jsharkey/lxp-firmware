/*
 * USART2 safety-CPU receiver glue. See include/inv/safety_rx_port.h.
 */
#include "inv/safety_rx_port.h"
#include "inv/safety_rx.h"
#include "inv/safety_cpu.h"      /* g_safety_bank */
#include "inv/uart2.h"

static inv_safety_rx_t g_rx;
static uint8_t   g_mode;
static uint32_t  g_fault, g_warn;
static uint32_t  g_last_ms;
static bool      g_seen;

void safety_rx_port_init(uint32_t baud)
{
    inv_safety_rx_init(&g_rx, g_safety_bank);
    g_mode = 0; g_fault = 0; g_warn = 0; g_last_ms = 0; g_seen = false;
    uart2_init(baud);
}

void safety_rx_port_poll(uint32_t now_ms)
{
    uint8_t b;
    while (uart2_rx_get(&b)) {
        if (inv_safety_rx_byte(&g_rx, b) == SAFETY_RX_FRAME) {
            g_mode  = g_rx.mode;
            g_fault = g_rx.fault;
            g_warn  = g_rx.warn;
            g_last_ms = now_ms;
            g_seen = true;
        }
    }
}

uint8_t  safety_rx_mode(void)          { return g_mode; }
uint32_t safety_rx_fault(void)         { return g_fault; }
uint32_t safety_rx_warn(void)          { return g_warn; }
uint32_t safety_rx_frames(void)        { return g_rx.frames_ok; }
uint32_t safety_rx_last_frame_ms(void) { return g_last_ms; }

bool safety_rx_link_ok(uint32_t now_ms, uint32_t timeout_ms)
{
    if (!g_seen)
        return false;                       /* no frame ever: link not up */
    return (uint32_t)(now_ms - g_last_ms) <= timeout_ms;
}
