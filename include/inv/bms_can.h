/*
 * Battery BMS over CAN1 — the inverter's view of the pack (docs/20).
 *
 * Split like the Modbus side: a TRANSPORT-AGNOSTIC decoder (src/can/bms_can.c)
 * that turns a received CAN frame into decoded pack state, plus a hardware port
 * (src/can/can_port.c) that brings up bxCAN CAN1, drains its receive FIFO and
 * sends the periodic keep-alive/request so the pack keeps streaming telemetry.
 *
 * Frame layouts are in include/inv/bms_can_map.h (standard little-endian preset).
 */
#ifndef INV_BMS_CAN_H
#define INV_BMS_CAN_H

#include <stdint.h>
#include <stdbool.h>

/* Decoded pack state (the subset the com-MCU consumes so far). Fields carry a
 * *_valid flag so a consumer only publishes what the pack has actually sent. */
typedef struct {
    uint8_t  soc;            /* state of charge, %  (0x355 [0:1]) */
    uint8_t  soh;            /* state of health, %  (0x355 [2:3]) */
    bool     soc_soh_valid;
} bms_pack_t;

/* Reset decoded state. */
void bms_can_init(bms_pack_t *pack);

/* Feed one received CAN frame into the decoder. Returns true if it was a known
 * telemetry frame that updated `pack`. */
bool bms_can_on_frame(bms_pack_t *pack, uint32_t id, const uint8_t *data, uint8_t dlc);

/* ---- hardware port (src/can/can_port.c) ---- */

/* Bring up CAN1 (remapped to PB8/PB9, docs/16) and an accept-all RX filter into
 * FIFO 0. Hardware-ack waits are bounded, so this also returns promptly under a
 * harness that does not model the bxCAN init handshake. */
void can_port_init(void);

/* Drain every frame pending in receive FIFO 0, calling on_frame for each
 * (polled; the stock firmware polls CAN1 with no IRQ — docs/20). */
void can_port_poll(void (*on_frame)(uint32_t id, const uint8_t *data, uint8_t dlc));

/* Transmit one standard-ID frame, non-blocking (dropped if no TX mailbox is
 * free — never spins waiting on hardware). Used for the keep-alive/request. */
void can_port_send(uint32_t std_id, const uint8_t *data, uint8_t dlc);

#endif /* INV_BMS_CAN_H */
