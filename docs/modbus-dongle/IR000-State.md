# IR 0 — State (operating mode)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See
> the [index](README.md). This is the register the datalogger reads to show the
> inverter's operating mode.

| reg | name | unit | range |
|---|---|---|---|
| IR 0 | State | — (bitmask) | see table |

## Where the data comes from

**The USART2 bank, and it is the one DSP-originated field in that bank.** The DSP
computes the real-time working-state byte; it hands it to the **safety CPU** over
SCI-C, which relays it to the ARM in the USART2 telemetry frame at **`BANK+0`**
(frame offset `+4`). The ARM's classifier `sub_0801b480` canonicalizes it into
`IR_STATE`, served to the dongle by the getter `sub_0803289c`.

- Bank/relay path: [`docs/33`](../33-usart2-telemetry-bank.md),
  [`docs/wiring/ARM-USART2`](../wiring/ARM-USART2.md),
  [`docs/wiring/DSP-SCI-C`](../wiring/DSP-SCI-C.md).
- ARM/DSP responsibility split: [`docs/22`](../22-arm-dsp-core-split.md)
  (`IR_STATE` = byte at `0x2000a0d8+0x90`, getter `sub_0803289c`).

The same `IR_STATE` value also **gates the power-path relays** inside the ARM
(run-enable follows the mode) — see [`docs/18`](../18-power-path-relays.md). That
is an internal consumer, not something the dongle sees.

## Operating modes (spec Table 9)

| code | mode | code | mode |
|---|---|---|---|
| `0x00` | Standby | `0x20` | AC Charge |
| `0x01` | Fault | `0x28` | PV + AC charge |
| `0x02` | Programming (FW update) | `0x40` | Battery off-grid |
| `0x04` | PV on-grid | `0x80` | PV off-grid *(unstable, not advised)* |
| `0x08` | PV Charge | `0x88` | PV charge + off-grid |
| `0x0C` | PV Charge + on-grid | `0xC0` | PV + battery off-grid |
| `0x10` | Battery on-grid | | |
| `0x14` | PV + Battery on-grid | | |

## Nuance

`State == 2` is **Programming** (firmware update), not "AC First". An earlier
relay-gating draft misread `== 2` as AC-First output-priority; corrected in
[`docs/18`](../18-power-path-relays.md)/[`docs/16`](../16-arm-io-map.md).
Output-priority is a *holding* register —
[`HR145-OutputPrioConfig`](HR145-OutputPrioConfig.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **Other tab**: `Status` = current status, `NextStatus` = next status. The manual's status-code table (§17.3) is the same code set as IR 0 but adds two the Modbus operating-mode table omits: `0x11` **Bypass** and `0x19` **PV Charge + Bypass**.
