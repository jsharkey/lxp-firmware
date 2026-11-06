/*
 * USART3 (ARM<->DSP link) RX demux classifier. See inv/dsp_rx.h and docs/39 T09.
 * Mirrors the factory USART3 RX framing gate (sub_0801c3e6): Modbus slave
 * (03/04/06/10) + DSP bootloader (21/22/23); everything else (incl. a 0x49
 * telemetry SOF) is rejected -- the ARM does not consume DSP 0x49 telemetry here.
 */
#include "inv/dsp_rx.h"

dsp_rx_class_t inv_dsp_rx_classify(uint8_t first, uint8_t func, uint8_t dev_addr)
{
    /* frame start: address must match this device, or 0 (broadcast) */
    if (first != dev_addr && first != 0)
        return DSP_RX_REJECT;

    switch (func) {
    case 0x03: case 0x04: case 0x06: case 0x10:
        return DSP_RX_MODBUS;
    case 0x21: case 0x22: case 0x23:
        return DSP_RX_BOOTLOADER;
    default:
        return DSP_RX_REJECT;     /* 0x01 (a 0x49 type-1 telemetry frame) lands here */
    }
}
