# ARM USART1 ↔ (peer open — not brought up this boot)

**Status: open link.** Research trail:
[`docs/25`](../25-modbus-register-spaces.md),
[`docs/16`](../16-arm-io-map.md).

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **USART1** `0x40013800`, pins **PA9 TX / PA10 RX** *(presumed)* | ~ pins |
| peer | **unknown** — "meter / console / ?" | ? |

## State

- **Not enabled this boot** on ceaa-07xx: `USART_BRR = 0x0000`, **UE = 0**. No
  baud, direction or peer established.
- Pins PA9/PA10 are *presumed standard* — **not hit by the GPIO init sweep**, so
  not independently confirmed.
- An ISR exists (IRQ37 `sub_08005370`), one of the five distinct non-default UART
  ISRs, but the port is not initialised.

> **Do not confuse with the MPPT controller's USART1.** All the rich "USART1 +
> `0x42`" analysis in [`docs/13`](../13-mppt-controller.md) is the **MPPT chip's
> own** USART1 on the power board ([`MPPT-USART1.md`](MPPT-USART1.md)), a
> different processor — not this ARM port.

## Open / unreconciled

- Whether USART1 is ever brought up (on another model/boot path), and its peer.
- **ISR-count discrepancy:** [`docs/25`](../25-modbus-register-spaces.md) finds
  **five** distinct non-default UART ISRs (incl. this USART1 ISR), whereas
  [`docs/05`](../05-dsp-link.md) / [`docs/12`](../12-6000xp.md) state "only
  USART3 is NVIC-vectored; the others are polled." Different analysis
  rounds/images; docs/25 (ceaa-07xx) is the later, most specific. Unreconciled.
