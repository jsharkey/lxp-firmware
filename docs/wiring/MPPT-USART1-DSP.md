# MPPT controller USART1 ↔ Control DSP

**Authoritative** for this link. Research trail:
[`docs/13`](../13-mppt-controller.md) (primary).

The solar DC-DC power stage runs on its **own** processor (the `mppt` image,
`CBAA`) — a separate chip from the ARM and the DSP. It publishes PV telemetry
over a Modbus-family UART. The master is the **DSP** (inferred), so PV V/I/P
reaches the ARM only indirectly: **MPPT → DSP → (safety CPU) → ARM**.

## Endpoints

| end | port | confidence |
|---|---|---|
| MPPT stage controller | **USART1** `0x40013800` (interrupt-driven) | ✔ (MPPT image) |
| Control DSP | *(its MPPT-facing SCI)* | ~ inferred (peer) |

The MPPT chip is an **STM32G0-class Cortex-M0+** (128 KB flash, HSI16 16 MHz),
proven by register-layout discriminators (modern USART ISR@+0x1C / TDR@+0x28,
GPIO base `0x50000000`, G0 NVIC IRQ9/IRQ27, FLASH KEYR@0x08). Its role
"MPPT/power-stage" is inferred from the `mppt` filename tag + peripheral mix
(TIM1 advanced PWM + DMA-ADC + Modbus serial, zero HMI/strings).

> **This is a distinct chip, not an ARM "com" variant and not the DSP.** Do not
> conflate the MPPT's own USART1 with the ARM's [`ARM-USART1`](ARM-USART1-open.md).

## Physical

- Interrupt-driven **USART1** carries the register link (USART1/2/3 + UART4 are
  init'd, but USART1 is the comms one). Pins/baud on the MPPT side not pinned.

## Framing — `0x42`

Modbus-family, **big-endian** 16-bit registers (helpers `0x08010798`/`…A6`),
standard table-driven Modbus RTU **CRC-16** (canonical `auchCRCHi/auchCRCLo`
tables, routine `0x08010750`):

```
0x42 ('B') SOF · [1]=0x01 class · addr · len · payload · CRC-16 hi · CRC-16 lo
total = len + 6 ; RTU-style idle-gap framing (~30 ticks)
```

Note CRC is appended **hi then lo** (opposite vanilla Modbus RTU). Class-1
payload = 16-byte header + typed records (types 0/1/2) = a telemetry report
(Vpv/Ipv/Ppv/status); the physical register meaning is not decoded.

## Direction & roles

**MPPT → DSP**, DSP = master/poller. The ARM never materialises `0x42`, has no
analog metering, and has only one TTL inter-MCU UART (USART3 = DSP). The DSP
aggregates PV/grid telemetry and forwards it to the ARM over USART3, with the
operating-state path relayed via the safety CPU on USART2 (see
[`ARM-USART2.md`](ARM-USART2-safety.md)).

## Remote update

The MPPT bootloader speaks the **same `0x21/0x22/0x23`** update vocabulary as the
DSP link (G0 FLASH unlock keys `0x45670123` / `0xCDEF89AB`). The ARM acts as a
`0x21/0x22/0x23` gateway: dongle → ARM → DSP → MPPT.

## Open

- **The `0x42` MPPT→DSP leg is not positively evidenced in the DSP images on
  hand** — neither decoded C28x image parses the CBAA `0x42` frame (possible
  product/version skew: MPPT image Aug 2025 vs DSP Mar–Apr 2025). The ARM-side
  inference (no direct MPPT↔ARM wire) is strong; the DSP-side confirmation is
  pending. The 18kPV DSP's SCI-C `'T'`/`'D'` link is a *different* link (the
  safety-CPU cross-check), not the CBAA `0x42` link.
