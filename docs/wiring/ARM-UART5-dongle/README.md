# ARM UART5 ↔ external "dongle" (ESP32-C3 datalogger)

> **Register surface:** [`registers.md`](registers.md) (in this directory) is the
> authoritative dongle Modbus register map — one file per register/group
> (`IR001_003-Vpv1_Vpv3`, `HR022-StartPVVolt`, …) alongside this wire doc.

**Authoritative** for this link. Research trail:
[`docs/26`](../../26-dongle-firmware.md) (dongle identity/role — primary),
[`docs/04`](../../04-modbus.md) (register/framing contract),
[`docs/08`](../../08-arm-dsp-config-protocol.md) (handler location),
[`docs/25`](../../25-modbus-register-spaces.md) (UART/baud table + register spaces).

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
> [`include/inv/modbus_map.h`](../../../include/inv/modbus_map.h) cite **19200**;
> UART5 reads **9600** post-boot. Dongle baud is field-configurable, so baud is
> **not** a port discriminator. A bus capture would settle the real rate — treat
> 9600 as the observed value for this image.

## Framing

EG4/Luxpower Modbus-RTU variant: `addr · func · SN[10] · body · CRC-16`,
**little-endian** fields, CRC poly `0xA001` / init `0xFFFF`, appended low byte
then high. (The 10-byte serial-number field and LE order are what distinguish
this "dongle" framing from the internal DSP framing — see
[`ARM-USART3.md`](../ARM-USART3-DSP/README.md).) Functions `0x03/0x04/0x06/0x10` served out of
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
([`docs/26`](../../26-dongle-firmware.md)). So the dongle can only surface what the
ARM already serves as a register — it cannot reach data the ARM leaves in private
RAM. This is why the per-battery BMS stats carried on CAN1 (`0x311–0x321` /
`0x370–0x381`) never come out here: the ARM buffers them but maps none to a
register ([`docs/34`](../../34-multi-battery-can.md)).

## Key functions / files

- Factory: handler `sub_0802afe2` @ `0x40005000`, buffer `0x20008ca4`.
- Reimplementation: transport-agnostic engine
  [`src/modbus/modbus.c`](../../../src/modbus/modbus.c), port
  [`src/modbus/modbus_port.c`](../../../src/modbus/modbus_port.c) over the UART5
  driver [`src/uart/uart5.c`](../../../src/uart/uart5.c), map
  [`include/inv/modbus_map.h`](../../../include/inv/modbus_map.h).

> **Port binding (reimplementation): on UART5 (T01, resolved).** Our Modbus
> slave runs on **UART5** (`modbus_port.c` → `uart5_init`), with the RS-485 DE on
> **PA15** driven high before the first TX byte and released on TC
> (`uart5_set_de`). USART3 is the DSP link's alone (`src/dsp/dsp_link_port.c`
> brings it up). Was a USART3 placeholder; moved in T01 ([`docs/39`](../../39-parity-roadmap.md)).

### Harness / oracle note (T01)

Dynamic re-proof on the `ceaa-07xx` image (`tests/arm_sim_modbus.py`): feeding an
EG4-Modbus read on **UART5** draws **no reply** from the factory in the harness —
its UART5 receive path (`sub_0802afe2`) is a scheduler task that never gets the
CPU without the RTOS running (**T02**). The factory **does** answer on **USART3**
(its NVIC-vectored DSP-facing slave ISR), serving the same register model.

So the harness has **two explicit masters, no auto-detection** (one UART each):
`ModbusDongle` drives **UART5** (our firmware's port), and `ModbusDsp` drives
**USART3** (the factory's reachable register-slave in the harness — the DSP
polling the ARM as a Modbus master; a valid register oracle until T02 lets the
factory's real UART5 task run). Each test picks the master for the image's port:
ours → `ModbusDongle`, factory → `ModbusDsp`. Never point `ModbusDsp`/a probe at
the factory's UART5 — its UART5 ISR consumes the request and disturbs the config
flash/persistence.

### Test coverage

Every common Modbus test (`tests/test_arm_sim.py`: register read/write, AC-First
status, time set/read-back, OptimalChg round-trip, cold-boot persistence) now
runs over this UART5 binding for our firmware and passes for both images. The DE
sequencing around TX is pinned by `test_modbus_de_toggles_around_tx`
(`tests/test_arm_sim_self_only.py`).

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

## Factory RX buffer (ceaa-07xx)

Per-frame linear RX buffer **200 B** at `0x2000bb80` (`sub_0801bf6a`, guard
`cmp #0xc8`), ISR `0x0801c0b0`. Our `src/uart/uart5.c` uses a 256 B ring (≥ the
factory's). See [`docs/47`](../../47-factory-ram-static-breakdown.md).
