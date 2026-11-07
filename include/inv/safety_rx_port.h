/*
 * USART2 safety-CPU receiver — hardware glue (docs/39 T05).
 *
 * Binds the pure frame parser (inv/safety_rx.h) to the USART2 driver (inv/uart2.h)
 * and the telemetry bank (g_safety_bank, inv/safety_cpu.h): poll drains the RX ring
 * and feeds each byte to the parser, which decodes complete frames into the bank.
 * The decoded operating mode + relayed fault/warn words are exposed for the state
 * classifier (inv_classify, see src/main.c); the last-good-frame timestamp supports
 * the rx-timeout -> comms-loss fault (T08).
 */
#ifndef INV_SAFETY_RX_PORT_H
#define INV_SAFETY_RX_PORT_H

#include <stdint.h>
#include <stdbool.h>

/* Bring up USART2 at `baud` and reset the parser (writing into g_safety_bank). */
void safety_rx_port_init(uint32_t baud);

/* Drain the USART2 RX ring and decode any complete frames. Call every loop with a
 * free-running millisecond base. */
void safety_rx_port_poll(uint32_t now_ms);

/* Latest decoded header, from the most recent CRC-valid frame (0 until one lands). */
uint8_t  safety_rx_mode(void);
uint32_t safety_rx_fault(void);
uint32_t safety_rx_warn(void);

/* Diagnostics / link health. */
uint32_t safety_rx_frames(void);          /* count of CRC-valid frames decoded      */
uint32_t safety_rx_last_frame_ms(void);   /* now_ms at the last decoded frame        */
/* True if a frame has been decoded within `timeout_ms` of `now_ms` (T08: a false
 * result is the comms-loss condition that raises E017). */
bool     safety_rx_link_ok(uint32_t now_ms, uint32_t timeout_ms);

#endif /* INV_SAFETY_RX_PORT_H */
