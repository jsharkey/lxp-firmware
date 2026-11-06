# Bootloader `0x21` / `0x22` / `0x23` — ARM → DSP firmware update

> **ARM→DSP**, a *separate* framing on this wire (not type-1 blocks). A distinct RX
> state machine handles it. See the [index](fields.md).

The firmware-update path to the DSP is three function codes, handled by the DSP's
sector-0 **bootloader** `FUN_00080aa8` (not the application comms task):

| func | role |
|---|---|
| `0x21` | **session start / erase** — `"EDSN"`-tagged |
| `0x22` | **program block** — write a flash page of new firmware |
| `0x23` | **verify / commit** |

- The DSP bootloader accepts **exactly these three** and **ACKs each**
  (`FUN_000810C5`); frame lengths match the ARM's extended table exactly.
- On the ARM side these are driven by a **separate RX state machine**
  `FUN_0801bbe0` (addr + func ∈ `{0x21,0x22,0x23}`) — distinct from the type-1
  config/telemetry state machine `FUN_0801bb0e`.
- **Endianness note:** the bootloader path uses *little*-endian readers
  (`FUN_000810E6`/`FUN_000810D7`) — unlike the big-endian config path on the same
  wire. Don't mix the readers.
- The ARM also **gateways MPPT firmware updates** through to the DSP along this
  path — see [`MPPT-USART1`](../../wiring/MPPT-USART1-DSP.md).

Background: [`docs/05`](../../05-dsp-link.md) (link id + bootloader identification),
[`docs/wiring/ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md).
