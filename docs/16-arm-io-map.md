# ARM "com" MCU — GPIO / IO map (EG4 12000XP, `ceaa-07xx`)

Status: **recovered by static + dynamic RE of the factory ARM image**
(`d673c5ed-ceaa-07xx_vE_260214`, the 07-series App at `0x08005000`). Every pin's
**direction/mode is proven** (read out of the `GPIO_Init` calls); peripheral-pin
assignments are **proven** from the STM32F103 alternate-function map plus the
active-peripheral scan; the **silkscreen purpose of the bare relay/LED/control
outputs is inferred** from the driver logic and flagged by confidence.

## MCU and method

- **STM32F103VE**, Cortex-M3, 100-pin, 512 KB flash @ `0x08000000`, RAM
  `0x20000000`. Only GPIO ports **A–E** are configured (no F/G) — consistent with
  the 100-pin package and `ldscripts/stm32f103ve.ld`.
- The firmware drives IO through the **ST StdPeriph library**. The four helpers
  were located by signature (`tools/gpio_map.py` auto-detects them):

  | helper | addr | body |
  |---|---|---|
  | `GPIO_Init(port, &InitStruct)` | `0x08014ebc` | decodes `{pin, speed, mode}` → `CRL`/`CRH` |
  | `GPIO_SetBits(port, mask)` | `0x08014fcc` | `str mask,[port,#0x10]` (BSRR) → pin HIGH |
  | `GPIO_ResetBits(port, mask)` | `0x08014fd4` | `str mask,[port,#0x14]` (BRR) → pin LOW |
  | `GPIO_ReadInputDataBit(port, mask)` | `0x08014fb0` | test `IDR & mask` → input |

- `tools/gpio_map.py` hooks those entries under Unicorn, calls every
  helper-caller while sweeping `r0`/`r1` (so wrapper dispatchers that pick a pin
  by argument take each branch), and records the live `(port, pin, mode)`.
  `tools/periph_map.py` lists the on-chip peripherals actually used. Both are
  read-only and run against `reference/com_flat.bin` (build it with
  `tools/hex2bin.py`, symbols with `tools/recurse.py`).

## On-chip peripherals in use

From `tools/periph_map.py` (base-address references): **USART1, USART2, USART3,
UART4, UART5, CAN1, SPI1, TIM1, TIM2, TIM3, TIM4, TIM8, RTC, IWDG, PWR, BKP,
AFIO, EXTI**. No I2C master transactions (so the settings store is not an I2C
EEPROM — SPI1 is the candidate; cf. [`docs/09`](09-dsp-persistence-and-clock.md)
on the ARM owning persistence). No ADC pin is configured as analog-in — the com
MCU does no analog metering (that is the DSP / `mppt` controller).

## Peripheral (alternate-function) pins — proven

AF-PP / its paired RX input, from the STM32F103 AF map. **Bold peer names are
confirmed by other docs; others follow the standard pin-out.**

| Pins | Peripheral | Use | Conf. |
|---|---|---|---|
| PA9 / PA10 | USART1 TX/RX | *(active; pins presumed standard — not hit by the init sweep)* | med |
| PA2 / PA3 | USART2 TX/RX | serial link | high |
| PB10 / PB11 | USART3 TX/RX | **DSP control link** (docs/05, docs/08) | high |
| PC10 / PC11 | UART4 TX/RX | serial link (meter / BMS-UART) | high |
| PC12 / PD2 | UART5 TX/RX | **external RS-485 dongle / Modbus** (docs/08) | high |
| PB8 / PB9 | CAN1 RX/TX (remap) | **battery BMS CAN bus** | high AF / med peer |
| PA5 / PA6 / PA7 | SPI1 SCK/MISO/MOSI | SPI bus (see CS pins below) | high AF |
| PA4, PC4 | SPI1 chip-selects (GPIO) | two SPI1 devices — **LCD controller + config EEPROM/flash** | high CS / med peer |
| PE9 / PE11 / PE13 / PE14 | TIM1 CH1–4 PWM (remap→PE) | **cooling fans** (HMI "Fan1–5 …") | high AF / med peer |
| PC7 | TIM3 CH2 PWM (remap) | single PWM — **buzzer** candidate | high AF / low peer |
| PD15 | TIM4 CH4 PWM (remap) | single PWM — aux (fan / LCD backlight) | high AF / low peer |

PE8/PE10/PE12/PE15 sit on TIM1's complementary/break pins but are configured as
**GPIO inputs**, not used as TIM1 outputs.

## Full pin inventory (all 54 configured pins)

Direction/mode is proven; "driver" is the function that sets/reads it; purpose
confidence noted. `sub_08032a46`/`sub_08032dee`/`sub_08032fc8` are the board
pin-init functions (main / comms / CAN groups).

### Inputs

| Pin | Mode | Reader | Purpose | Conf. |
|---|---|---|---|---|
| PA8, PA11, PC8, PC9 | IN-PU | `sub_08016af0` (debounced) | **front-panel keys** (UP/DOWN/ENTER/ESC) | high |
| PA1, PB0, PE12 | IN-FLOAT | `sub_08012848` | digital detect / config straps | med |
| PC13 | IN-FLOAT | `sub_0801ae14` | detect input | low |
| PD8 | IN-FLOAT | `sub_0801ac2c` | detect input | low |
| PB14 | IN (shared) | `sub_0802e49a` | status/feedback (also in the PB output bank) | low |
| PB5, PC0, PC1, PE8, PE10, PE15 | IN | — (no reader hit) | inputs / straps / unused | low |

### Outputs — comms transceiver direction/enable (inferred from UART adjacency)

| Pin | Driver | Associated link | Conf. |
|---|---|---|---|
| PA0 | `sub_0801b560` (from USART3 TX path `sub_0801b976`) | USART3 / DSP dir-or-enable | med |
| PC2 | `sub_0801bde4` (adjacent to USART2 driver `0x0801bd34`) | USART2 RS-485 direction | med |
| PA15 | `sub_0801c0b8` (between UART4/UART5 drivers) | UART4/5 (dongle) direction | med |

### Outputs — power-path relays / contactors (GPIO proven; identity inferred)

| Pin(s) | Driver → logic | Inferred role | Conf. |
|---|---|---|---|
| PA12 + PB3 | `sub_080334fc` / `sub_08033536` via `sub_08018a7c` (grid-connect debounce, `[+0xbc]` bit20 & bits29-30==2, ~50-tick) | **main grid / EPS transfer contactors** | med |
| PB2 + PC6 | `sub_080334ae` via `sub_08016ec6` (gated by `IR_STATE` `0x2000d0e4+0xa0` + override `0x2000da6c` bit4) | **inverter run-enable / bypass** | med |
| PC5 | `sub_0803348e` via `sub_08017022` (multi-condition, 100/1501-tick debounce) | slow AC relay — gen-input / AC-couple | low-med |
| PD11 | `sub_08033556` via `sub_08035ef2` (config bits + debounce) | **EPS/backup or dry-contact relay** | low-med |

> **Full relay analysis in [`docs/18`](18-power-path-relays.md).** The byte at
> `0x2000d0e4+0xa0` is the live **operating mode = IR_STATE (input reg 0)**, a
> bitmask (value-matched to [`states.h`](../include/inv/states.h)) — not the
> output-priority setting. So PC6 is gated by the **working mode**, and
> `0x2000da6c` is the **AutoTest/manual relay-override** word. (An earlier draft
> read `+0xa0 == 2` as "AC First"; that is `STATE_PROGRAMMING` — corrected in
> docs/18. docs/14's AC-First *time-window* conclusion is unaffected.)

### Outputs — HMI / indicators / misc

| Pin(s) | Driver | Inferred role | Conf. |
|---|---|---|---|
| PB1, PB12, PB13, PB15 | `sub_0801154a` (set HIGH as a bank) | status-LED / indicator bank (HMI "LED Ctr/Mode") | med |
| PD14 | `sub_08016af0` (key scan) + `sub_0801154a` | LCD backlight or key-column strobe | med |
| PD10 | `sub_0801acf4` (set HIGH once per main loop) | enable / run / heartbeat line | med |
| PA4, PC4 | SPI1 CS cluster (`sub_0801c6d0…`) | SPI1 device selects (LCD / EEPROM) | high |
| PB6 + PB7 | `sub_08037c7a…dba` (PB6 out, PB7 in/out, bit-banged) | **bit-banged 1-/2-wire bus** (temp sensor / share line) | med |

## The "Dry Control" dry-contact relay — status

`MENU_DRY_CONTROL` (HMI item 91) configures a user dry-contact relay. It is one
of the bare relay outputs above — **`PD11` is the leading candidate** (an
independent, config-gated, debounced relay not tied to the grid-connect or
output-priority logic), with `PC5` second. This **cannot be pinned from firmware
alone** without (a) the holding-register → settings-offset for "Dry Control" and
(b) the board schematic / silkscreen. The decisive experiment, reproducible with
the committed harness: in Unicorn, set the Dry-Control setting (and sweep the
condition it follows) and watch which `GPIO_SetBits`/`ResetBits` pin tracks it —
the same technique `tools/emu_acfirst.py` uses for the AC-First window.

## Open items

- Confirm the USART1 pins (PA9/PA10 presumed; not hit by the init sweep) and
  which peer each UART serves (USART3=DSP and UART5=dongle are known; USART1/
  USART2/UART4 peers — meter, BMS-UART, console — are not yet pinned).
- Resolved in [`docs/18`](18-power-path-relays.md): `0x2000d0e4+0xa0` = IR_STATE
  (reg 0); `0x2000da6c` = AutoTest/manual relay-override. Remaining: fix each
  relay's silkscreen identity (grid vs EPS vs gen vs dry).
- Pin the dry contact (method above) and the SPI1 peers (LCD vs EEPROM) and the
  PB6/PB7 bit-banged bus.
- Map the EXTI inputs (external-interrupt lines) — the scan shows EXTI/AFIO use
  but this pass covered polled IO, not the interrupt pin config.
