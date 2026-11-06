# Wiring — the inverter's inter-processor and external links

**This directory is the source of truth for how the processors and peripherals
are wired together.** Each physical link has its own doc here, named
`<ENDPOINT>-<PORT>.md` (e.g. [`ARM-USART3.md`](ARM-USART3.md),
[`DSP-SCI-C.md`](DSP-SCI-C.md)). When a numbered analysis doc (`docs/NN-*.md`)
and a doc here disagree about a wire, **the doc here wins** — the numbered docs
are the research trail, these are the distilled, reconciled result. Fix the
wiring doc first, then the numbered doc.

> Scope: this project reimplements only the **ARM "com" MCU**. Links on the DSP
> and MPPT sides are documented here because they frame what the ARM sees, but
> only the ARM side is ours to build.

**Confidence legend** (used in every table): **✔** proven from firmware (the end
is noted when only one side is proven) · **~** strong inference · **?** open.

## System block diagram — the processors and their links

Six processors have been identified: four on the inverter main/power boards, the
BMS in the battery pack, and the external datalogger dongle.

```
                             +------------------------------+
                             |  EG4 datalogger / cloud      |
                             |  "dongle"  ESP32-C3 (ext.)   |   master of the
                             +---------------+--------------+   external RS-485 bus
                                             | UART5  PC12/PD2            [✔]
                                             | 9600 RS-485 (DE PA15)
   battery pack(s)                           | EG4 Modbus (LE + 10-byte SN)
  +---------------------+  CAN1  PB8/PB9      | ARM = slave
  | BMS  HC32F460       |<------------------->|
  | (ARM-CAN1)          |  classic 11-bit CAN |
  +--------+------------+  0x3xx up / 0x30x dn |
           | RS-485 pack-to-pack              |
           : (daisy chain)                    v
  meter? ----- UART4 PC10/PC11 ------>+--------------------------------------------+
  (open [?])   2400 RS-485 (DE PA15)  |   ARM "com" MCU  (STM32F103VE-class)       |
  console? --- USART1 PA9/PA10 ------>|   comms . HMI . supervisor . relays        |
  (off this boot [?])                 |   << THIS PROJECT >>  no analog metering   |
                                      +--+-----------------------------------+--+--+
                 USART3 PB10/PB11        |                                   |  |
                 19200 TTL   [✔]         |                       SPI1 PA5/6/7|  | GPIOB PB12-15
                 ARM->DSP config (0x41)  |                       +CS PA4  [✔]|  | bit-banged [✔]
                 +bootloader 21/22/23    |                            |      |  |
                 DSP->ARM telem (0x49)   | (= DSP SCI-B)              v      |  v
                                         v                     +-----------+ | +------------------+
                                  +--------------------------+  | config    | | | graphic LCD      |
                                  |  TI C2000 Control DSP    |  | NOR flash | | | 240x160 mono     |
                                  |  (F2837x) real-time FSM  |  | (ARM-SPI1)| | | MIPI-DCS, 1bpp   |
                                  |  measures PV & grid      |  +-----------+ | | (ARM-LCD)        |
                                  +--+-------------------+---+                | +------------------+
                MPPT USART1 0x42      | DSP = master  [~]|  SCI-C 9600 TTL     |
                big-endian Modbus [✔] v  of both links   |  'T'/'D'   [✔ DSP]  v
                (peer=DSP, [~])    +------------------+   |  cross-check  +------------------------+
                                   | MPPT controller  |   |               | redundant / safety CPU |
                                   | CBAA, STM32G0    |   +-------------->| (part unknown)         |
                                   | (MPPT-USART1)    |      SCI-A 9600   | votes + gates inverter |
                                   | PV V/I/P telem   |      bulk dump    | (DSP-SCI-C)            |
                                   +------------------+      (DSP-SCI-A)  +-----------+------------+
                                                                                     | USART2 PA2/PA3
                                                                                     | 19200 RS-485
                                                                                     | (DE PC2), RX-only [✔]
                                                                                     | safety CPU -> ARM:
                                                                                     | mode + its own grid/PV
                                                                                     | measurements + fault (E027)
                                                                                     v  (ARM-USART2)
                                                                            (to ARM USART2, above)
```

> **Key topology fact (settled).** The ARM's classified operating state, core
> input registers and fault word are built from the **safety CPU** over USART2 —
> *not* directly from the DSP. The safety CPU cross-checks the DSP's redundant
> samples over **SCI-C** and relays a consolidated mode + its **own** grid/PV
> measurements + the fault word (agreement bit **E027**) + grid warnings to the
> ARM over **USART2**. (The W008 FW-version-mismatch warning is ARM-computed, not
> relayed.) The DSP's *own* `0x49` telemetry still reaches the ARM directly on
> **USART3** (SCI-B). See [`ARM-USART2.md`](ARM-USART2.md),
> [`DSP-SCI-C.md`](DSP-SCI-C.md) and the bank field map in
> [`docs/33`](../33-usart2-telemetry-bank.md).

## The links at a glance

| Link doc | ARM port (base) | pins | peer | electrical / baud | framing | direction | conf. |
|---|---|---|---|---|---|---|---|
| [ARM-USART3](ARM-USART3.md) | USART3 `0x40004800` | PB10/PB11 | **Control DSP** (SCI-B) | TTL, 19200 8N1 | EG4 type-1 block (BE, SN-less) + `0x21/22/23` bootloader | ARM→DSP config/boot; DSP→ARM `0x49` telem | ✔ |
| [ARM-USART2](ARM-USART2.md) | USART2 `0x40004400` | PA2/PA3 (DE PC2) | **redundant/safety CPU** | RS-485, 19200, **RX-only** | EG4 type-1 (BE, CRC-16) | safety CPU→ARM | ✔ |
| [ARM-UART5](ARM-UART5.md) | UART5 `0x40005000` | PC12/PD2 (DE PA15) | external **dongle** (ESP32-C3) | RS-485, 9600 8N1 | EG4 Modbus (LE + 10-byte SN) | dongle = master, ARM = slave | ✔ |
| [ARM-CAN1](ARM-CAN1.md) | CAN1 `0x40006400` | PB8/PB9 (remap) | **battery BMS** (HC32F460) | CAN, ~500 kbit/s *(unconfirmed)* | classic 11-bit, SMA/Pylontech family | BMS→ARM `0x3xx`; ARM→BMS `0x30x/0x400` | ✔ pins / ~ baud |
| [ARM-SPI1](ARM-SPI1.md) | SPI1 | PA5/PA6/PA7, CS PA4 | **config NOR flash** | SPI master | SPI NOR cmds; 6-slot journaled store | ARM ↔ flash (read+write) | ✔ (ARM) |
| [ARM-LCD](ARM-LCD.md) | GPIO (GPIOB) | PB12/13/14/15 | **graphic LCD** panel | bit-banged 4-wire serial | MIPI-DCS, 240×160 1bpp | ARM→panel | ✔ |
| [ARM-UART4](ARM-UART4.md) | UART4 `0x40004c00` | PC10/PC11 (DE PA15) | *meter? (open)* | RS-485, 2400 | *(EG4 family, presumed)* | open | ? |
| [ARM-USART1](ARM-USART1.md) | USART1 `0x40013800` | PA9/PA10 *(presumed)* | *open* | *off this boot (UE=0)* | — | — | ? |
| [DSP-SCI-C](DSP-SCI-C.md) | DSP SCI-C | — | **redundant/safety CPU** | TTL, ~9600 | `'T'` in / `'D'` out, 30-byte, CRC-16 BE | DSP = master | ✔ (DSP) |
| [DSP-SCI-A](DSP-SCI-A.md) | DSP SCI-A | — | *open* | TTL, ~9600 | bulk `LS4_RAM` strided records | DSP→? | ✔ exists / ? peer |
| [MPPT-USART1](MPPT-USART1.md) | MPPT USART1 `0x40013800` | — | **Control DSP** *(inferred)* | UART, Modbus-family | `0x42` SOF, big-endian registers | MPPT→DSP (DSP = master) | ✔ MPPT / ~ peer |

Every serial link above reuses the **EG4/Luxpower Modbus frame family**
(`addr func [SN?] body CRC-16/0xA001`), but they are **separate wires**, not one
shared bus — each UART is a self-contained port. Two framings coexist: the
external dongle gets **little-endian + 10-byte SN**; the internal DSP link gets
**big-endian + block-tagged, SN-less** frames. The ARM's one dual-mode
serializer (`sub_0803373c`, flag `0x2000aa0b` bit 0) switches between them.

## Local GPIO (not inter-processor links)

Panel keys, relays, fans and indicators are driven directly on ARM GPIOs. The
**full 54-pin inventory and the recovery method live in
[`docs/16-arm-io-map.md`](../16-arm-io-map.md)**; the relay drive logic is in
[`docs/18-power-path-relays.md`](../18-power-path-relays.md). Summary:

| IO | pins | notes | conf. |
|---|---|---|---|
| Front-panel keys | PC9 Up, PA8 Down, PA11 Enter, PC8 Esc | IN-PU, debounced `sub_08016af0` | ✔ |
| Power-path relays | PA12+PB3, PB2+PC6, PC5, PD11 | 4 logic fns; gated by operating mode + grid status; silkscreen identity inferred — see docs/18 | ✔ pins / ~ role |
| Cooling fans | PE9/PE11/PE13/PE14 | TIM1 CH1–4 PWM (remap→PE) | ✔ AF / ~ peer |
| Buzzer | PC7 | TIM3 CH2 PWM (remap) | ~ |
| Aux PWM | PD15 | TIM4 CH4 — fan / LCD backlight | ~ |
| 1-/2-wire bus | PB6 (out) + PB7 (in/out) | bit-banged; temp sensor / share line | ~ |
| Status LED / heartbeat | PB1, PD10, PD14 | indicator / run line / LCD-backlight-or-strobe | ~ |

> The reimplementation's front-panel display is the GPIOB graphic LCD in
> [`ARM-LCD.md`](ARM-LCD.md) (`src/hmi/lcd_tft.c`). An earlier 20×4 HD44780 I²C
> character-LCD stand-in on **PE0/PE1** (a reimplementation convenience, never
> factory wiring) was removed once that panel was decoded — the hardware has no
> character LCD and no display I²C.

## Cross-cutting corrections (read before trusting an old numbered doc)

These are resolved here; some numbered docs still carry the earlier reading in a
table cell even where a correction note follows.

- **USART2's peer is the safety CPU, not a DSP SCI and not DSP-relayed.** The
  grid/PV *measurements* in the USART2 bank are the **safety CPU's own**
  (commit `896f4aa`). `docs/22`'s table cell still prints "PV voltage = DSP
  telemetry, verbatim"; that cell is stale — the correction block below it and
  [`ARM-USART2.md`](ARM-USART2.md) are right.
- **The external dongle is UART5, not USART3.** USART3 is the ARM↔DSP link.
  Earlier `docs/25`/`docs/22-modbus-multiplexing` drafts put the dongle on
  USART3; retracted. See [`ARM-UART5.md`](ARM-UART5.md).
- **The ARM↔DSP link is the EG4 *type-1 block* protocol, not standard Modbus.**
  The "standard Modbus / func-3+SN" reading described the *dongle* channel.
  See [`ARM-USART3.md`](ARM-USART3.md).
- **The factory LCD is a bit-banged GPIOB bus, not SPI1.** SPI1 is the config
  flash. See [`ARM-LCD.md`](ARM-LCD.md) and [`docs/28`](../28-factory-hmi.md).
- **DSP SCI-A is not the telemetry port to the ARM.** SCI-A carries an unrelated
  bulk dump; the ARM-facing DSP telemetry is SCI-B (= USART3). See
  [`DSP-SCI-A.md`](DSP-SCI-A.md).
- **CAN1 RX: polled vs interrupt-driven is unreconciled.** `docs/16`/`docs/20`
  body say polled; `docs/19`/`docs/20` correction say interrupt-driven (FMPIE0).
  Tracked in [`ARM-CAN1.md`](ARM-CAN1.md).

## Still open

- USART1 and UART4 peer identities (and whether USART1 is ever brought up).
- CAN1 bit-rate (decode the BMS's HC32 `SBT`; expected 500 kbit/s).
- The literal copper pin-pairing ARM-USART3 ↔ DSP-SCI-B (schematic-level).
- The safety CPU's part number, and whether its SCI-C peer and the USART2 peer
  are physically the same MCU (role-level inferred, not firmware-provable).
- Confirm the `0x42` MPPT→DSP leg from a DSP image (absent in the two on hand).
- The DE/direction GPIOs (PA0 for USART3?, PA15 shared by UART4/5) — firmware
  association is inferred.
