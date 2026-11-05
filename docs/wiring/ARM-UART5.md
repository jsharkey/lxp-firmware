# ARM UART5 ↔ external "dongle" (ESP32-C3 datalogger)

**Authoritative** for this link. Research trail:
[`docs/26`](../26-dongle-firmware.md) (dongle identity/role — primary),
[`docs/04`](../04-modbus.md) (register/framing contract),
[`docs/08`](../08-arm-dsp-config-protocol.md) (handler location),
[`docs/25`](../25-modbus-register-spaces.md) (UART/baud table + register spaces).

The external EG4 Modbus port: a plug-in datalogger polls the inverter over
RS-485. On this bus the **inverter is the slave**.

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **UART5** `0x40005000`, pins **PC12 TX / PD2 RX** | ✔ |
| external dongle | ESP32-C3 (RISC-V) RS-485 Wi-Fi/BLE datalogger, HIDO IoT SDK | ✔ (dongle image) |

Both ends are proven: the ARM handler statically, and the dongle's own firmware
(project `esp32_dongle`, build `E_V2_12`) analyzed separately.

## Physical

- **RS-485 half-duplex, 9600 8N1** (UART5 `BRR 0x186a`). Direction/DE candidate
  **PA15** (shared with UART4; firmware association ~ inferred).
- Dongle side proven RS-485 half-duplex with RTS as DE
  (`uart_set_mode(..., UART_MODE_RS485_HALF_DUPLEX)`, `RS485Service_Init`).
- ISR IRQ53 `sub_0801c0b0`.

> **Baud discrepancy (flagged, not resolved).** The EG4 spec and
> [`include/inv/modbus_map.h`](../../include/inv/modbus_map.h) cite **19200**;
> UART5 reads **9600** post-boot. Dongle baud is field-configurable, so baud is
> **not** a port discriminator. A bus capture would settle the real rate — treat
> 9600 as the observed value for this image.

## Framing

EG4/Luxpower Modbus-RTU variant: `addr · func · SN[10] · body · CRC-16`,
**little-endian** fields, CRC poly `0xA001` / init `0xFFFF`, appended low byte
then high. (The 10-byte serial-number field and LE order are what distinguish
this "dongle" framing from the internal DSP framing — see
[`ARM-USART3.md`](ARM-USART3.md).) Functions `0x03/0x04/0x06/0x10` served out of
the central settings store `0x20009854` by handler **`sub_0802afe2`** (RX buffer
`0x20008ca4`).

**Register spaces (the "126" trap):** the function code selects an independent
number line — `0x03/0x06/0x10` = **holding** (RW settings), `0x04` = **input**
(RO telemetry). The same number means unrelated things in each (e.g. HR 126-131
= OptimalChg_DisChg time table; IR 126 = a status word, bit 8 = "AC-First window
active"). Always say which space (`HR` vs `IR`). Query rule: ≤ 40 registers and
no crossing a 40-register group boundary, else exception `0x02`.

## Direction & roles

**Dongle = RS-485 bus master (polls); ARM = Modbus slave.** A master cannot sit
on USART3 (where the ARM is itself the master of the DSP link) — this is the
decisive argument that the dongle is on UART5.

The dongle is a **transparent byte conduit**, not a register-aware poller: its
firmware exposes a generic `RS485Service` → `SendBytes(port, buf, len)` plus a
`UartRxTask` that relay **opaque** EG4-Modbus frames between its cloud/BLE side
and this bus, with no on-device register map or function-code dispatch
([`docs/26`](../26-dongle-firmware.md)). So the dongle can only surface what the
ARM already serves as a register — it cannot reach data the ARM leaves in private
RAM. This is why the per-battery BMS stats carried on CAN1 (`0x311–0x321` /
`0x370–0x381`) never come out here: the ARM buffers them but maps none to a
register ([`docs/34`](../34-multi-battery-can.md)).

## Key functions / files

- Factory: handler `sub_0802afe2` @ `0x40005000`, buffer `0x20008ca4`.
- Reimplementation: transport-agnostic engine
  [`src/modbus/modbus.c`](../../src/modbus/modbus.c), port
  [`src/modbus/modbus_port.c`](../../src/modbus/modbus_port.c), map
  [`include/inv/modbus_map.h`](../../include/inv/modbus_map.h).

> **Known port mis-binding (reimplementation).** Our Modbus slave is currently
> bound to **USART3** as a placeholder (`modbus_port.c` → `uart3_init`), because
> USART3 was the factory's only NVIC-vectored EG4-framed UART and looked like the
> external port. The engine is transport-agnostic; the fix is to **move the port
> binding USART3 → UART5** and wire the RS-485 DE (PA15) into `mb_port_set_tx()`,
> leaving USART3 to the DSP. Tracked in [`docs/04`](../04-modbus.md).

## Corrections folded in

- **Retracted:** "dongle Modbus slave is on USART3 / UART5-at-9600 unlikely." The
  USART3 probe reply was the ARM's dual-mode serializer in dongle mode and/or our
  own harness binding; the UART5 silence was a false negative (the handler is a
  gated scheduler task a cold probe can't start). Corrected map: **dongle =
  UART5, USART3 = ARM↔DSP**.
- Even earlier draft claimed dongle + DSP "share USART3" — mistook our
  placeholder for the factory; the factory uses separate UARTs.

## Open

- Real on-wire baud (bus capture).
- Firmware confirmation of PA15 as the UART5 DE pin.
- `IR 126` labelled `IR_EGEN_ALL_H` in the map but used as a status word in
  ceaa-07xx — do not assume `IR 126 = energy` for this image.
