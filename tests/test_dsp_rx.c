/* Host tests for the USART3 RX demux classifier (docs/39 T09). make test */
#include "inv/dsp_rx.h"
#include <stdio.h>

static int g_fail = 0, g_run = 0;
#define CHECK(c, m) do { g_run++; if (!(c)) { \
    printf("  FAIL: %s (%s:%d)\n", m, __FILE__, __LINE__); g_fail++; } } while (0)

int main(void)
{
    const uint8_t A = 1;   /* our device address */

    /* Modbus requests (func 03/04/06/10) to our address -> MODBUS */
    CHECK(inv_dsp_rx_classify(A, 0x03, A) == DSP_RX_MODBUS, "addr+03 -> MODBUS");
    CHECK(inv_dsp_rx_classify(A, 0x04, A) == DSP_RX_MODBUS, "addr+04 -> MODBUS");
    CHECK(inv_dsp_rx_classify(A, 0x06, A) == DSP_RX_MODBUS, "addr+06 -> MODBUS");
    CHECK(inv_dsp_rx_classify(A, 0x10, A) == DSP_RX_MODBUS, "addr+10 -> MODBUS");
    CHECK(inv_dsp_rx_classify(0, 0x03, A) == DSP_RX_MODBUS, "broadcast(0)+03 -> MODBUS");

    /* DSP bootloader frames (func 21/22/23) -> BOOTLOADER */
    CHECK(inv_dsp_rx_classify(A, 0x21, A) == DSP_RX_BOOTLOADER, "addr+21 -> BOOTLOADER");
    CHECK(inv_dsp_rx_classify(A, 0x22, A) == DSP_RX_BOOTLOADER, "addr+22 -> BOOTLOADER");
    CHECK(inv_dsp_rx_classify(A, 0x23, A) == DSP_RX_BOOTLOADER, "addr+23 -> BOOTLOADER");

    /* a 0x49 type-1 telemetry frame is NOT consumed: */
    CHECK(inv_dsp_rx_classify(0x49, 0x01, A) == DSP_RX_REJECT, "0x49 SOF -> REJECT (wrong address)");
    CHECK(inv_dsp_rx_classify(A, 0x01, A) == DSP_RX_REJECT, "type byte 0x01 -> REJECT (not a func)");

    /* other invalid function codes and wrong addresses -> REJECT */
    CHECK(inv_dsp_rx_classify(A, 0x02, A) == DSP_RX_REJECT, "func 0x02 -> REJECT");
    CHECK(inv_dsp_rx_classify(A, 0x05, A) == DSP_RX_REJECT, "func 0x05 -> REJECT");
    CHECK(inv_dsp_rx_classify(2, 0x03, A) == DSP_RX_REJECT, "wrong address -> REJECT");

    printf("%s: %d/%d checks passed\n", g_fail ? "FAILED" : "OK", g_run - g_fail, g_run);
    return g_fail ? 1 : 0;
}
