# ARM CAN1 ↔ battery BMS

**Authoritative** for this link. Research trail:
[`docs/20`](../20-battery-bms-firmware.md) (frame contract, BMS side — primary),
[`docs/16`](../16-arm-io-map.md) (ARM-side binding),
[`include/inv/bms_can_map.h`](../../include/inv/bms_can_map.h) (committed C contract).

The one peer the ARM reads **first-hand** (it does no analog metering of its
own): the battery pack's BMS, on CAN1. The DSP is not involved — the full
init/RX/parse/TX path is in the ARM image.

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **CAN1** `0x40006400`, pins **PB8 RX / PB9 TX** (remap) | ✔ pins |
| battery BMS | HDSC **HC32F460**-class Cortex-M4, EG4-LL LFP pack | ✔ (BMS image) |

CAN1 is remapped to PB8/PB9 because the default PA11/PA12 clash with the AC
transfer relay on PA12. Both ends proven (`BATT_IN280-Z03T13.bin` analyzed).

## Physical

- **Classic CAN** via a transceiver (not RS-485).
- **Bit-rate: ~500 kbit/s, unconfirmed** — the BMS's HC32 `SBT` bit-timing is
  not yet decoded; `BMS_CAN_BAUD_EXPECTED 500000u` is provisional.

## Framing

Standard 11-bit identifiers, SMA/Victron/Pylontech-family layout. Byte order is
**preset-dependent** (the standard preset is little-endian; another preset packs
big-endian). The pack selects one of 8 brand presets (`P01-EG4 … P07-LUX …
P08-SMA`); our inverter pairs with `P07-LUX` / `P01-EG4`.

| direction | IDs | payload |
|---|---|---|
| BMS → inverter | `0x351` | charge/discharge V & I limits |
| | `0x355` | SOC / SOH |
| | `0x356` | battery V / I / T |
| | `0x359` / `0x35A` | alarms / protection bitfields |
| | `0x35B/0x35C/0x35E/0x35F` | ext status / request flags / mfr name / fw+cap |
| | `0x311-0x321`, `0x370-0x381` | extended |
| inverter → BMS | `0x300` | request |
| | `0x301` | config / handshake |
| | `0x305` | keep-alive |
| | `0x400` | command |

## Direction & roles

The battery is the TX master of its `0x3xx` telemetry; the inverter transmits
`0x30x` / `0x400` control frames. Decoded SOC/V/I/limits/alarms are written into
state RAM and mirrored to Modbus input registers (e.g. `0x355`→IR5, `0x356` V→IR4
/ I→IR98 / T→IR103, `0x351` chg-V→IR83, `0x359`→IR99/100/96).

## Working-limit derivation (T11a)

The `0x351` charge-voltage limit is **not** forwarded raw. The inverter serves the
**lesser** of the pack's limit and the `ChargeVoltRef` setting (HR 99):

```
IR 83 (ChargeVoltRef, 0.1 V) = min(0x351 charge-V limit, HR 99)
```

Factory-oracled black-box on `ceaa-07xx` (sweep `0x351` vs HR 99 → all `min()`).
The "~57.4 V clamp" once attributed to a cell-count max is just HR 99's power-on
default (574 = 57.4 V); HR 99 = 590 raises the ceiling to 590, so there is no
separate hard clamp. Reimplemented as the pure function
[`inv_bms_charge_volt_ref()`](../../src/bms/bms_limits.c)
([`include/inv/bms_limits.h`](../../include/inv/bms_limits.h)), wired in `on_can_frame`.

The pack's other `0x351` fields (max charge/discharge current → IR 81/82,
discharge-voltage limit → IR 84) are **not published** on this image in the harness
(they stay `0` under the same sweep). Whether that is genuine or a scheduler-task
publish that needs the full RTOS (**T02**) is unresolved — see
[`IR081_106-BMS`](ARM-UART5-dongle/IR081_106-BMS.md#working-charge-voltage-derivation-t11a).
The inverter→BMS control-frame TX (`0x305` keep-alive etc.) is **T11b**.

## Key functions / files

- Factory: init `sub_08022660` (+ filters `sub_080227b6`); RX `sub_08005758` →
  ring of 200 × 20-byte records @ `0x200051ac`; parser `sub_0802a760`
  (scheduler task); TX `sub_0800574c` → `sub_080228c0`.
- BMS side: TX builder `FUN_0002a0bc`, RX dispatcher `FUN_0002314c`, ID table
  @ `0x00031a20`.
- Reimplementation: [`src/can/can_port.c`](../../src/can/can_port.c)
  (`can_port_init/poll/send`), decoder
  [`src/can/bms_can.c`](../../src/can/bms_can.c), working-limit derivation
  [`src/bms/bms_limits.c`](../../src/bms/bms_limits.c), map
  [`include/inv/bms_can_map.h`](../../include/inv/bms_can_map.h); wired in
  [`src/main.c`](../../src/main.c) `can_port_init()` / `on_can_frame`.

## Open / unreconciled

- **RX polled vs interrupt-driven — contradiction.**
  [`docs/16`](../16-arm-io-map.md) says the bus is **polled** (IRQ vectors 19-22
  → default handler). [`docs/20`](../20-battery-bms-firmware.md) (and
  [`docs/19`](../19-gpio-test-harness.md)) **correct** this: the factory arms
  `CAN1->IER = 0x2` (FMPIE0) and receives in the `CAN1_RX0` ISR. docs/20 is the
  later finding; not yet reconciled into docs/16. (Our reimplementation polls
  FIFO0 each loop regardless.)
- CAN bit-rate (decode HC32 `SBT`).
- Which `Pnn` preset / endianness the attached pack is configured for.
