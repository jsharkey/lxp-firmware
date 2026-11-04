# The `mppt` image (`CBAA`) — a fourth, distinct processor

Analysis of the attached firmware `169a5158-CBAA-1Cxxxx_mppt_250805.hex`.

**Verdict: this is NOT another flavour of the "com" MCU.** It is a *different,
smaller* STM32F103-class part running a bare-metal power-control loop, built with
the same EG4 toolchain and boot conventions as the com firmware. Its vendor
filename role-tag — **`mppt`** — is a peer of the `com` and `dsp` tags on the
images we already have, and its peripheral profile (advanced-timer PWM + ADC +
DMA, no HMI) is exactly that of a solar DC-DC **MPPT / power-stage controller**.
So the user's guess is right: it is a dedicated chip for the PV MPPT stage, not a
new model of the processor this project reimplements.

All *structural* facts below are direct reads of the image (`tools/hex2bin.py`
then word/vector decode). The *role* ("MPPT controller") is an inference from the
filename role-tag plus the peripheral mix — strong, but not an in-band string.

## Why it is clearly not the com MCU

| | com MCU (12000XP/18kPV/6000XP) | this `CBAA` image |
|---|---|---|
| Part | STM32F103**VE** high-density (512 KB flash, 64 KB RAM) | STM32F103x**B**-class medium-density (**128 KB** flash, ~20 KB RAM) |
| Image size | 244 KB–587 KB | **42.5 KB** of populated flash |
| Initial MSP | `0x2000AF88` … (tens of KB) | **`0x200007A0`** boot / **`0x200021C8`** app (≈2 KB / ~8.6 KB) |
| HMI / menu text | ~442 strings, font tables, menu enum | **zero** human-readable strings |
| Interrupts wired | USARTs, timers, EXTI, … (comms + UI) | **just TIM1_CC + EXTI3** (a control loop) |
| Role tag in filename | `…_com_vE_…` | **`…_mppt_…`** |

The com MCU is a communications/HMI/supervisor; this is a tiny real-time
controller. Different silicon, different job.

## Same EG4 firmware family, though

Despite being a different chip and role, it is unmistakably from the same vendor
codebase/toolchain as the com images:

- **Identical reset stub idiom** — `ldr r0,=SystemInit; blx r0` then
  `ldr r0,=__main; bx r0`, with a CMSIS-F1 `SystemInit` that writes `SCB->VTOR`
  (`0xE000ED08`). This is the same Keil-armcc / scatter-loaded signature noted in
  `docs/12-6000xp.md`.
- **`SN__` signature block** — the top-of-flash word at `0x0801FFFC` is `SNAM`,
  matching the family scheme `SNEC` (12000XP) / `SNCC` (6000XP) / `EAA1` (18kPV).
- **4-char model code** — `CBAA` (filename) appears as an ASCII tag at
  `0x080140EC`, the same convention as `ceaa` / `ccaa` / `FAAB`.
- **STM32F1 peripheral map** — `RCC @0x40021000`, `FLASH_ACR @0x40022000`, FLASH
  IAP unlock key `0x45670123`, GPIO/AFIO/USART bases all F1-exact.

## Memory map (direct reads)

128 KB part (last populated byte is exactly `0x0801FFFF`). The populated flash
comes in four segments — a **bootloader + application** split, with `SNAM` /
`NOTB` partition tags at the boundaries:

| region | addr range | contents |
|---|---|---|
| Bootloader | `0x08000000 .. 0x080020FF` | vector table (MSP `0x200007A0`, reset `0x08001FED`), flash-IAP writer (key `0x45670123`) |
| — tag | `0x08002018` | `SNAMNOTB` signature + constant `0x00F42400` (= 16,000,000) |
| App vectors | `0x08003600 .. 0x080041FF` | **application vector table @`0x08003800`** (MSP `0x200021C8`, reset `0x08014095`); `SNAM` tag @`0x08004000` |
| App code | `0x0800C600 .. 0x080141FF` | the control firmware; `NOTB` tag @`0x0800C800`, `CBAA` tag @`0x080140EC` |
| Top signature | `0x0801FF00 .. 0x0801FFFF` | `SNAM` at the 128 KB boundary (`0x0801FFFC`) |

> The exact bootloader→app VTOR handoff is not fully resolved — both reset stubs'
> `SystemInit` write `VTOR = 0x08000000`, yet a valid second vector table sits at
> `0x08003800`. The `SNAM`/`NOTB` tags look like boot-slot magic. Left as an open
> detail; it doesn't change the identification.

## The control-loop fingerprint (why "MPPT / power stage")

The application vector table (`0x08003800`) enables exactly two peripheral
interrupts:

- **IRQ 27 — TIM1_CC** (`0x080132E8`): TIM1 is the **advanced-control timer**, the
  one used to generate (complementary) PWM for a switch-mode converter. A
  capture/compare interrupt is the classic duty-cycle / control-tick of a DC-DC
  regulation loop.
- **IRQ 9 — EXTI3** (`0x0800E9DC`): a single external edge line — the shape of a
  hardware **fault / over-current / sync** input.

The power-control driver block lives at `0x0800DC00..0x0800F900` and is written as
HAL-style register helpers around:

- **ADC1** (`0x40012400`) — PV voltage / current / bus sensing,
- **TIM1** (`0x40012C00`) — converter PWM,
- **DMA1** (`0x40020000`) — ADC→memory streaming (continuous sampling),

with ready-flag spin loops (ADC calibration / clock lock). **USART1**
(`0x40013800`, the most-referenced peripheral) is the inter-processor link — how
this controller reports MPPT telemetry to and takes setpoints from the main
DSP/com side. There is **no** UART-RX interrupt and no display/keypad code at all.

That combination — TIM1 PWM + ADC + DMA + a fault EXTI + one UART, and nothing
else — is a textbook dedicated power-stage controller, consistent with the `mppt`
role tag.

## Scope / what this means for the project

This image is **out of scope** for the current reimplementation, which targets
only the com MCU (see README). It does **not** belong in `include/inv/variant.h`:
that abstraction is for *models of the com MCU* (same silicon, same codebase), and
this is neither. It is better understood as a new **peer processor** alongside the
TI C2000 control DSP and the com MCU — the EG4 platform splits firmware by role
(`com` / `dsp` / `mppt`), and this is the `mppt` one.

Open questions a schematic or a live unit would answer:
- Exact STM32F103xB part number (and whether it's a clone, e.g. GD32/APM32).
- How many PV trackers this one MCU drives, and whether there is one such MCU per
  MPPT or one for all (the 12000XP/6000XP have 2 MPPTs, the 18kPV has 3).
- The USART1 framing to the DSP/com side (is it the same EG4 Modbus-family link as
  `docs/05-dsp-link.md`, with its own setpoint/telemetry commands?).
- Decode of the `0x00F42400` (16 MHz) constant — HSE crystal vs a derived clock.
