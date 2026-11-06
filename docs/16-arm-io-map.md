# ARM "com" MCU — GPIO / IO map (EG4 12000XP, `ceaa-07xx`)

Status: **recovered by static + dynamic RE of the factory ARM image**
(`d673c5ed-ceaa-07xx_vE_260214`, the 07-series App at `0x08005000`). Every pin's
**direction/mode is proven** (read out of the `GPIO_Init` calls); peripheral-pin
assignments are **proven** from the STM32F103 alternate-function map plus the
active-peripheral scan; the **silkscreen purpose of the bare relay/LED/control
outputs is inferred** from the driver logic and flagged by confidence.

## System block diagram & per-link details → `docs/wiring/`

The overall system block diagram and the per-port ARM link table have **moved to
the wiring source-of-truth** at [`docs/wiring/README.md`](wiring/README.md), with
one doc per physical link — e.g. [`ARM-USART3`](wiring/ARM-USART3.md) (DSP),
[`ARM-USART2`](wiring/ARM-USART2.md) (safety CPU), [`ARM-UART5`](wiring/ARM-UART5.md)
(dongle), [`ARM-CAN1`](wiring/ARM-CAN1.md) (BMS), [`ARM-SPI1`](wiring/ARM-SPI1.md)
(config flash), [`ARM-LCD`](wiring/ARM-LCD.md) (panel). Defer to `docs/wiring/` for
what each port connects to and how.

This doc keeps the **full 54-pin inventory** and the **recovery method** below —
the IO-map substance that the wiring docs reference.

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
  read-only and run against `reference/ceaa-07xx_vE_260214.bin` (build it with
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
| PB12, PB13, PB14, PB15 | `sub_080114d2` / `sub_08011698` (bit-banged) | **graphic-LCD 4-wire serial bus** — PB12 SCLK, PB13 SDA, PB14 DC, PB15 /CS (a 240×160 monochrome MIPI-DCS LCD, 1bpp 8px/byte; **not** on SPI1, which is the config flash). Corrects the earlier "status-LED bank" read — see [`docs/28`](28-factory-hmi.md) | high |
| PB1 | `sub_0801154a` (set HIGH) | status-LED / indicator (HMI "LED Ctr/Mode") | low-med |
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

## CAN1 ↔ battery BMS — the ARM handles it (not the DSP)

The battery pack's BMS firmware ([`docs/20`](20-battery-bms-firmware.md), a
separate HC32 MCU) sits on **CAN1 / PB8-PB9** (row above). The question "who on
the inverter side drives that bus?" resolves cleanly to **this ARM com-MCU** —
the full init / RX / parse / TX path is in the ARM image, serviced from the
scheduler (there is **no CAN interrupt**: IRQ vectors 19-22 all point at the
shared default handler, so the bus is **polled**).

| stage | function | detail |
|---|---|---|
| **init** | `sub_08022660` (+ filters `sub_080227b6`) | configures bxCAN `0x40006400` and the filter banks `0x40006600…` (`FMR`/`FS1R`/`FFA1R`/`FA1R`/bank 0); brought up via `sub_08039018` |
| **RX (polled)** | `sub_08005758` | polls the RX-FIFO level (`sub_08022b1c(CAN1, 2)`) and reads each frame via `sub_080229fe` into a **ring of 200 × 20-byte records at `0x200051ac`** (write index `0x2000a9df`, wraps at `0xc8`=200; record = `{id, dlc, data[8]}`) |
| **parse** | `sub_0802a760` | scheduler task (registered by `sub_0803e4c8`); consumes the ring and dispatches on CAN ID — brackets the `0x350–0x360` core set (`0x351/0x355/0x356/0x359/0x35a/0x35c/0x35f`) plus the `0x300`, `0x370–0x38c` and `0x4xx` (Pylontech) ranges, exactly the TX IDs [`docs/20`](20-battery-bms-firmware.md) recovered from the pack; writes decoded SOC/V/I/limits/alarms into state RAM |
| **TX** | `sub_0800574c` → `sub_080228c0` | sends a frame from `0x2000a650`; driven from the same CAN task (`sub_0802a760` → `sub_0802a2f8` → `sub_0800574c`) |

So the inverter↔battery CAN contract documented from the pack side in `docs/20`
is **consumed and produced here, on the ARM**, via the `0x200051ac` RX ring and
the `sub_0802a760` parser — this is the "CAN1 reader" `docs/20` asked to bind to.
For the reimplementation, the battery-telemetry module lives on the ARM side next
to the Modbus/HMI/DSP-link code, keyed off [`include/inv/bms_can_map.h`](../include/inv/bms_can_map.h).

**Not yet decoded:** the CAN **bit-timing/baud** (`CAN_BTR` in `sub_08022660`) —
`docs/20` expects 500 kbit/s; and which `Pnn` preset / endianness the pack is
configured for (a battery-side setting, see `docs/20`).

## Open items

- Confirm the USART1 pins (PA9/PA10 presumed; not hit by the init sweep) and
  which peer each UART serves. Known: **USART3 = DSP** (SCI-B: config + bootloader),
  **UART5 = dongle** (independently corroborated by the dongle's own firmware —
  an RS-485 **half-duplex master** datalogger, so the ARM is the slave; see
  [`docs/26`](26-dongle-firmware.md), which also rules out USART3 for the dongle),
  and **USART2 = the redundant / safety CPU** (EG4-framed `type=1` frame carrying the
  operating mode + PV/grid V/F **and** the E027/W008 cross-check status into
  `0x20009e54`; the ARM's core input registers + fault word come from here — peer
  pinned in [`docs/30`](30-safety-cpu-arm-handoff.md), see also [`docs/22`](22-arm-dsp-core-split.md)).
  USART1/UART4 peers (meter, BMS-UART, console) are still not pinned.
- `IR_STATE` (reg 0) = byte at **`0x2000a0d8+0x90`** (getter `sub_0803289c`,
  written by the classifier `sub_0801b480`) — see [`docs/22`](22-arm-dsp-core-split.md).
  (Supersedes an earlier `0x2000d0e4+0xa0` note, which was a phantom address.)
  `0x2000da6c` = AutoTest/manual relay-override. Remaining: fix each relay's
  silkscreen identity (grid vs EPS vs gen vs dry).
- Pin the dry contact (method above) and the SPI1 peers (LCD vs EEPROM) and the
  PB6/PB7 bit-banged bus.
- Map the EXTI inputs (external-interrupt lines) — the scan shows EXTI/AFIO use
  but this pass covered polled IO, not the interrupt pin config.
