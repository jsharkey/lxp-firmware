# The `mppt` image (`CBAA`) — a fourth, distinct processor

> **Authoritative wiring:** the MPPT↔DSP serial link is distilled in [`docs/wiring/MPPT-USART1.md`](wiring/MPPT-USART1.md). This doc remains the full characterization of the MPPT processor.

Analysis of the attached firmware `169a5158-CBAA-1Cxxxx_mppt_250805.hex`.

**Verdict: this is NOT another flavour of the "com" MCU.** It is a *different,
smaller* MCU — an **STM32G0-class Cortex-M0+** — running a bare-metal power-control
loop, and it talks to another processor over a **Modbus-family UART link**. Its
vendor filename role-tag — **`mppt`** — is a peer of the `com` and `dsp` tags on
the images we already have, and its peripheral profile (advanced-timer PWM +
DMA-driven ADC + Modbus serial, no HMI) is exactly that of a solar DC-DC
**MPPT / power-stage controller**. So the user's guess is right: a dedicated chip
for the PV MPPT stage, not a new model of the processor this project reimplements.

> **Correction note:** an earlier revision of this file mis-identified the part as
> an STM32F103 (and read the `0x50000000` block as USB-OTG). The USART peripheral
> uses the *modern* register layout (status `ISR` at `+0x1C`, `TDR` at `+0x28`),
> which rules out the STM32F1 UART; the interrupt map and the GPIO base at
> `0x50000000` identify it as **STM32G0** (see "Chip identification" below). The
> structural facts have been re-derived accordingly.

All *structural* facts below are direct reads of the image (`tools/hex2bin.py`
then word/vector decode + Capstone). The *role* ("MPPT controller") is an
inference from the filename role-tag plus the peripheral mix — strong, but not an
in-band string.

## Why it is clearly not the com MCU

| | com MCU (12000XP/18kPV/6000XP) | this `CBAA` image |
|---|---|---|
| Part | STM32F103**VE** high-density, Cortex-**M3** (512 KB flash, 64 KB RAM) | **STM32G0-class, Cortex-M0+** (**128 KB** flash, small RAM) |
| Image size | 244 KB–587 KB | **42.5 KB** of populated flash |
| Initial MSP | `0x2000AF88` … (tens of KB) | **`0x200007A0`** boot / **`0x200021C8`** app (≈2 KB / ~8.6 KB) |
| HMI / menu text | ~442 strings, font tables, menu enum | **zero** human-readable strings |
| Interrupts wired | USARTs, timers, EXTI, … (comms + UI) | **just USART1 + DMA1** (serial link + ADC sampling) |
| Role tag in filename | `…_com_vE_…` | **`…_mppt_…`** |

The com MCU is a communications/HMI/supervisor; this is a tiny real-time
controller. Different silicon, different core, different job.

## Chip identification — STM32G0 (Cortex-M0+)

Every discriminator lines up with STM32G0 and excludes the F1/F3 guesses:

| evidence | reading |
|---|---|
| `SystemInit` writes `SCB->VTOR` (`0xE000ED08`) | core has VTOR → Cortex-M0+/M3/M4 (not M0) |
| USART status reg at **`+0x1C`** (`ISR`), `RXNE`=bit5 / `TC`=bit6 / `TXE`=bit7; data out at **`+0x28`** (`TDR`), in at `+0x24` (`RDR`), clear at `+0x20` (`ICR`) | the **modern** USART IP (G0/F0/F3/F7/L/…), **not** the F1/F2/F4 `SR`/`DR` layout |
| GPIO ports at **`0x50000000` / `0x50000400` / `0x50000800` / `0x50000C00`** (A/B/C/D); `str [port,#0x28]` = `BRR` | G0 GPIO base is `0x50000000` (F0 is `0x48000000`; F1 is `0x40010800`) |
| `ADC1 @0x40012400`, `TIM1 @0x40012C00`, `DMA1 @0x40020000`, `USART1 @0x40013800`, `RCC @0x40021000`, `FLASH @0x40022000` | all exact on the G0 map |
| used IRQ slots: **9 = DMA1_Channel1**, **27 = USART1** (VT @`0x08003800`) | the G0 NVIC numbering |
| recurring constant `0x00F42400` = **16 000 000** | G0's **HSI16** (16 MHz) system clock |

128 KB flash with ≥4 USARTs points at the larger G0 line (e.g. STM32G0B1xB). A
GD32/compatible clone can't be ruled out from the binary alone, but the map is
G0-exact.

## Memory map (direct reads)

128 KB part (last populated byte is exactly `0x0801FFFF`). The populated flash
comes in four segments — a **bootloader + application** split, with `SNAM` /
`NOTB` partition tags at the boundaries:

| region | addr range | contents |
|---|---|---|
| Bootloader | `0x08000000 .. 0x080020FF` | vector table (MSP `0x200007A0`, reset `0x08001FED`), flash-IAP writer (key `0x45670123`), a Modbus CRC-16 table pair |
| — tag | `0x08002018` | `SNAMNOTB` signature + constant `0x00F42400` (= 16,000,000 = HSI16) |
| App vectors | `0x08003600 .. 0x080041FF` | **application vector table @`0x08003800`** (MSP `0x200021C8`, reset `0x08014095`); `SNAM` tag @`0x08004000` |
| App code | `0x0800C600 .. 0x080141FF` | the control + comms firmware; `NOTB` tag @`0x0800C800`, `CBAA` tag @`0x080140EC`, a second Modbus CRC-16 table pair |
| Top signature | `0x0801FF00 .. 0x0801FFFF` | `SNAM` at the 128 KB boundary (`0x0801FFFC`) |

The firmware is clearly the same EG4 vendor lineage as the com images: the reset
stub is the familiar `ldr;blx`→SystemInit / `ldr;bx`→`__main` idiom, the
top-of-flash word is `SNAM` (matching the `SN__` family scheme — `SNEC` 12000XP /
`SNCC` 6000XP), and the 4-char model code `CBAA` is embedded, as `ceaa` / `ccaa` /
`FAAB` are on the others.

> The exact bootloader→app VTOR handoff is not fully resolved — both reset stubs'
> `SystemInit` write `VTOR = 0x08000000`, yet a valid second vector table sits at
> `0x08003800`. The `SNAM`/`NOTB` tags look like boot-slot magic. Left as an open
> detail; it doesn't change the identification.

## The control-loop fingerprint (why "MPPT / power stage")

The application vector table (`0x08003800`) enables exactly two peripheral
interrupts, and they tell the whole story:

- **IRQ 9 — DMA1_Channel1** (`0x0800E9DC`): the handler polls DMA1 (`0x40020000`),
  clears the flag, then **averages a batch of ADC samples and applies a
  calibration scale** (`(hi+lo)/2 · gain >> 10 · …`, reading per-channel calib
  words from RAM). This is the **PV sensing** path — ADC → DMA ring → scaled
  engineering units, the classic MPPT measurement front end.
- **IRQ 27 — USART1** (`0x080132E8` → `0x0801323A`): a serial ISR that tests
  `ISR.RXNE/TXE/TC` and drives the RX/TX byte handlers — the comms link (below).

`TIM1` (`0x40012C00`, the advanced-control timer) is configured by the init block
at `0x0800DF40`+ for **converter PWM**; it runs in hardware (no CC interrupt
needed), with the duty updated from the sensing loop. So the architecture is:
**TIM1 PWM out → ADC senses PV V/I → DMA batches samples → DMA ISR scales them →
duty update** — a textbook digital DC-DC / MPPT regulator. There is no display,
keypad, or menu code anywhere.

## UART comms: a Modbus-family register link (answers "does it publish stats?")

**Yes — strong, direct evidence.** This firmware runs an interrupt-driven serial
protocol and exposes register data for another processor to read/parse:

- **Four UARTs initialised.** A generic `uart_init(base, cfg)` (`0x0800E67C`) is
  called for **USART1 (`0x40013800`), USART2 (`0x40004400`), USART3 (`0x40004800`)
  and UART4 (`0x40004C00`)**. USART1 is the most-referenced peripheral in the
  image and is the interrupt-driven one.
- **RX/TX ring buffers + byte primitives.** TX enqueues into a 60-byte frame
  buffer (`ctx@0x200019F0`: buffer `+0x3C`, head `+0x7A`, count `+0x7E`) and the
  ISR shifts bytes out via `TDR` (`str byte,[USART+0x28]`, `0x0801308C`), toggling
  `CR1.TXEIE`. RX reads `RDR` and feeds a frame parser.
- **Big-endian 16-bit registers.** The frame helpers `0x08010798` (BE16) and
  `0x080107A6` (BE24/32) assemble values **most-significant-byte first** — the
  Modbus / network byte order. Values are handled as `uint16` registers and stored
  into a per-port context.
- **Standard Modbus RTU CRC-16.** The image contains the canonical
  `auchCRCHi`/`auchCRCLo` 256-byte table pair (byte-exact to the Modicon spec) —
  at `0x08001C58`/`0x08001D58` in the bootloader and `0x08013ACC`/`0x08013BCC` in
  the app. The CRC routine at `0x08010750` is the textbook table-driven form
  (`crc=0xFFFF`; `i = hi ^ byte`; `hi = lo ^ auchCRCHi[i]`; `lo = auchCRCLo[i]`;
  return `hi<<8|lo`). (This is why a search for the bit-wise `0xA001` polynomial
  comes up empty — the implementation is table-driven.)
- **Register/command dispatch.** A frame processor (`0x0800E606`) bounds-checks a
  command index against 12 and indexes a table at `0x08013F54`; the RX parser
  pulls fields from fixed frame offsets (bytes 4, 5, 9, 0xC–0xF, payload from
  0x14).

So the MPPT controller behaves as a **Modbus(-family) slave**: a master polls it
over UART, and it answers with CRC-checked, big-endian register frames carrying
its telemetry (PV voltage/current/power, status) — i.e. it **publishes statistics
for another firmware to read and parse**, exactly as hypothesised.

> **The master is the DSP, not the com MCU** (resolved from the ARM side — see
> [`docs/22`](22-arm-dsp-core-split.md)). The com MCU's PV registers are fed by
> the **DSP** over USART2 (PV **voltage** verbatim; PV **power** the ARM computes
> from the DSP-supplied V·I), and the com MCU configures no analog inputs and has
> no UART carrying raw MPPT frames. So the path is **MPPT → DSP → ARM**: the MPPT
> publishes to the DSP, the DSP aggregates PV/grid telemetry and forwards it to
> the com MCU.

One nuance: the CRC-16 and big-endian registers are pure Modbus, but the frame has
a **fixed-offset layout** (header bytes 0x00–0x13, data from 0x14) rather than the
variable-length Modbus-RTU PDU (`addr/func/len/…`). That matches the EG4 internal
link described in `docs/05-dsp-link.md` — a Modbus-derived framing with the
vendor's own command set — rather than vanilla Modbus RTU on the wire.

### Decoded USART1 frame layout and command set

Recovered from the RX state machine (`0x08013114`), the frame dispatcher
(`0x08013968`), the record decoder (`0x08013340`) and the TX builder
(`0x080138E0`). Per-UART comms context is a struct at `0x200019F0` (RX buffer at
`+0x00`, write index `+0x78`, expected length `+0x7C`, busy lock `+0x82`, RX-idle
tick `+0x80`; the TX ring is at `+0x3C`).

**Outer frame (same for RX and TX):**

| offset | size | field | notes |
|---|---|---|---|
| 0 | 1 | `0x42` (`'B'`) | start-of-frame; byte-0 ≠ `0x42` is dropped |
| 1 | 1 | `0x01` | frame class / protocol id; the dispatcher routes **only** class `0x01` (to the telemetry parser) |
| 2 | 1 | `addr` | node/port id — stored, **not** range-checked (so no slave-address filtering here) |
| 3 | 1 | `len` | payload length |
| 4 … 3+`len` | `len` | payload | |
| 4+`len` | 1 | CRC-16 **hi** | Modbus RTU CRC-16 over bytes `[0 … 3+len]` |
| 5+`len` | 1 | CRC-16 **lo** | **big-endian** (hi first) — note: vanilla Modbus RTU sends lo first |

`total = len + 6` (2 sync + addr + len + 2 CRC), minimum 7. The receiver is
framed by **silence**: an idle tick (`0x0801392E`) resets the parser after ~30
ticks without a complete frame — the Modbus-RTU inter-frame-gap idea. On a
complete frame the dispatcher recomputes the CRC over `len+4` bytes and **rejects
on mismatch**, then checks `byte[1]==1` before parsing.

**Class-1 payload = fixed header + a stream of typed records:**

- bytes `4…0x13` — a ~16-byte header (a byte at 4, two big-endian 32-bit words at
  5 and 9, more fields at `0xC…0x13`) copied into the status struct at
  `0x20001CC0`.
- bytes `0x14 …` — back-to-back **records**, each `=[type:u8][positional fields]`,
  walked by `0x08013340`. Values are big-endian; each decoded record OR-s an
  "updated" bit into the event mask at `0x20001D82` for the main loop.

| record `type` | → destination struct | payload shape |
|---|---|---|
| `0` | `0x20001CAC` (+ `0x20001CC0`) | 3× BE16, 4× u8, BE16 + a validated BE16 (via `0x8012D28`) — the largest record |
| `1` | `0x20001CFC` | u8 + 4× BE16 |
| `2` | `0x20001B74` (`+0x2C…+0x34`) | 5× BE16 |

So class 1 is a **telemetry report**: a header plus one or more register groups
(types 0/1/2), each landing in its own RAM structure. The physical meaning of each
register (which BE16 is Vpv, Ipv, Ppv, temperature, status…) is **not** decoded
here — that needs the vendor register map or a live bus capture — but the framing,
the CRC, and the record/command structure above are read directly from the code.

**Transmit path (`0x080138E0`):** build the body into the TX buffer at
`0x20001BB4`, compute the Modbus CRC-16 (`0x0801074C`), append it big-endian
(hi then lo), then enqueue (`0x080130A8`) into the USART1 TX ring; the `TXE`
interrupt drains it a byte at a time to `TDR`. Outgoing frames use the identical
`0x42 0x01 … CRC` envelope.

> Likely the same family as the ARM↔DSP link in `docs/05-dsp-link.md` (Modbus
> CRC-16, big-endian, fixed framing). Worth cross-checking the start byte (`0x42`
> vs that link's), the big-endian-CRC convention, and whether the record types map
> onto its `0x21/0x22/0x23` commands.

### Remote firmware update — the bootloader DOES speak `0x21/0x22/0x23`

**Yes: the ARM can reflash this MPPT MCU over the UART, using the same
`0x21/0x22/0x23` update vocabulary as the DSP link (`docs/05`).** The command set
lives in the **bootloader** (the `0x08000000` image), not the app — the app only
accepts `byte[1]==0x01` telemetry frames (`cmp #0x21/#0x22/#0x23` appears *only*
in the bootloader region).

The bootloader command router (`0x08000204`) reads the command from `frame[1]`
and routes:

| cmd | handler | action (direct reads + analogy to `docs/05`) |
|---|---|---|
| `0x21` | `0x08000242` | **session start** — captures the target image's address / length / CRC fields from the frame (words at payload offsets `0xC` and `0x10`, via BE readers `0x8000916`/`0x8000908`) into update state (`0x2000037C…0x20000388`); prepares/erases flash |
| `0x22` | `0x0800031C` | **program block** — writes the payload to flash |
| `0x23` | `0x080004D4` | **verify / commit** — checks the programmed image, marks the app valid, resets into it |

Supporting machinery, all read straight from the bootloader:

- **FLASH IAP driver.** Unlock writes `KEY1=0x45670123` / `KEY2=0xCDEF89AB` to
  `FLASH_KEYR` (`0x080006C4`), then erase/program via `FLASH_SR`/`FLASH_CR`. The
  register offsets used — `KEYR@0x08`, `SR@0x10`, `CR@0x14` — are the **STM32G0**
  FLASH layout (another G0 confirmation; F1 differs).
- **ACK frames.** After each command the bootloader builds a reply in the same
  `0x42 <cmd> … CRC16` envelope (echoes the command + a status byte + a 16-bit
  field, then the Modbus CRC) — `0x08000140`+.
- **Software reset** via `SCB->AIRCR = 0x05FA0004` (`0x080000B8`) — used to jump
  into the freshly programmed app. The *app* has the identical reset sequence
  (`0x08012028`), so the running app can bounce itself into the bootloader.
- **App-valid gate.** The bootloader reads the `NOTB` marker at `0x0800C800`
  (`0x08000AD4`) to decide run-app vs. stay-in-update — the same `"NOTB"`
  build-config scheme as the ARM com bootloader in `docs/05`.

So the end-to-end remote-update path is: the ARM gets the MPPT into bootloader
mode (the app can self-reset; the bootloader stays in update mode when the app is
marked invalid), then streams `0x21` (begin/erase) → `0x22`×N (program) → `0x23`
(verify/commit), each as a CRC-checked `0x42` frame, and the bootloader reboots
into the new image.

What's **proven** here (direct reads): the `0x21/0x22/0x23` dispatch, the FLASH
unlock/erase/program driver, the CRC-checked ACK framing, the `NOTB` app-valid
gate, and the soft-reset. What's **inferred** (strong — by the handler structure
plus the `docs/05` DSP analogy): the exact field semantics inside each command
(image addr/len/CRC in `0x21`, block layout in `0x22`, the commit checks in
`0x23`) and the precise trigger that first drops the app into the bootloader.
Confirming those, and whether the CRC seed / `"EDSN"`-style tag match the DSP
link, would come from a live capture — note this image carries **no** `"EDSN"`
tag, so the session magic differs from the DSP's.

## How MPPT telemetry reaches the ARM (cross-check vs the `ceaa-07xx` ARM image)

Cross-correlated the MPPT image with the factory **ARM "com" image**
(`…ceaa-07xx_vE_260214…`, md5 `ccc5172a…`, the 07-series App at `0x08005000`).

**Finding: there is no direct MPPT↔ARM wire. The MPPT reports to the DSP; the ARM
reads the consolidated PV telemetry from the DSP.** So the GPIO that carries MPPT
statistics *into the ARM* is the **ARM↔DSP link — USART3, pins `PB10` (TX) /
`PB11` (RX)** (docs/16), not a pin pair to the MPPT.

Evidence, all from the ARM image:

- **The ARM never speaks the MPPT's protocol.** The MPPT frames start with
  `0x42`; the byte `0x42` is never materialised or compared anywhere in the ARM
  image (nor is the DSP-telemetry SOF `0x49` an immediate — the ARM matches SOFs
  via pooled constants, but there is simply no `0x42` path).
- **The ARM has exactly one internal TTL inter-MCU UART.** Its configured UARTs,
  read out of the init (`sub_08032d68` + call sites) and cross-checked to docs/16:

  | ARM UART | baud | pins | transceiver | peer |
  |---|---|---|---|---|
  | USART3 | 19200 | PB10/PB11 | TTL (no DE pin) | **DSP control link** (internal) |
  | USART2 | 19200 | PA2/PA3 | **RS-485** (DE on `PC2`, driven in its ISR `0x0801BDE4`) | **DSP-domain telemetry** (DSP→ARM, RX) — see docs/22/23 |
  | UART4 | 2400 | PC10/PC11 | RS-485 (DE on `PA15`) | external (meter / BMS-UART) |
  | UART5 | 9600 | PC12/PD2 | RS-485 (DE on `PA15`) | **external RS-485 dongle / Modbus** |

  Only USART3 is a plain point-to-point TTL link — the DSP. USART2/UART4/UART5 all
  toggle an RS-485 direction GPIO, i.e. they are external multidrop buses, not an
  on-board link to the MPPT.

  > Peer updates since this table was first written: **UART5 = the external dongle**
  > is confirmed from the dongle's own firmware (an RS-485 half-duplex *master*
  > datalogger — [`docs/26`](26-dongle-firmware.md)), with its ARM-side handler
  > `sub_0802afe2` at `0x40005000` ([`docs/08`](08-arm-dsp-config-protocol.md)); and
  > **USART2** is now identified as the DSP→ARM telemetry link, not an unidentified
  > external bus ([`docs/22`](22-arm-dsp-core-split.md), [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md)).
- **The ARM does no analog metering** (docs/16: no ADC analog-in pins). It cannot
  measure PV itself; the numbers must arrive from a measuring peer.
- **The DSP writes the ARM's telemetry register array** (docs/05, docs/08): the
  USART3 parser (`0x0801BA98`, ctx `0x2000AF60`) ingests DSP→ARM telemetry frames
  (SOF `0x49`, docs/10) and populates the input-register array the Modbus slave
  serves.

So the data path is: **MPPT ⇄ DSP** (the MPPT's USART1 `0x42` link faces the DSP,
the other power-board processor) **→ DSP ⇄ ARM over USART3** (`PB10`/`PB11`). The
MPPT's raw per-channel records are consolidated by the DSP before the ARM sees
them.

### Field labels from the ARM side

Because the ARM exposes the PV telemetry as its Modbus **input registers**, those
give the authoritative labels + scaling for the quantities the MPPT ultimately
feeds (`include/inv/modbus_map.h`):

| quantity | IR | scale | note |
|---|---|---|---|
| PV1 / PV2 voltage | `IR_VPV1=1`, `IR_VPV2=2` | **0.1 V** | (`IR_VPV3=3` only on the 3-MPPT 18kPV) |
| PV1 / PV2 power | `IR_PPV1=7`, `IR_PPV2=8` | **1 W** | |
| DC bus voltage | `IR_VBUS1=38`, `IR_VBUS2=39` | 0.1 V | |
| PV energy today | `IR_EPV1_DAY=28`, `IR_EPV2_DAY=29` | 0.1 kWh | |
| PV energy total | `IR_EPV1_ALL_{L,H}=40/41`, `…=42/43` | 0.1 kWh | 32-bit L/H pair |

Notable: **there is no PV-current register** in the EG4 map — the ecosystem
publishes `Vpv` and `Ppv`, not `Ipv`. So the MPPT measures PV current internally
(it needs it to run the tracker and to compute `Ppv = Vpv·Ipv`) and reports
`Vpv`/`Ipv` (or `Vpv`/`Ppv`) to the DSP; only `Vpv` and `Ppv` surface at the ARM.

Applying those scalings to the MPPT records decoded above (types 0/1/2 of
big-endian `u16`s), the **likely** per-field mapping — to confirm against the DSP
image or a live capture — is: the `0.1 V`-scaled `u16`s (raw ~2000–5000 for
200–500 V) are `Vpv1/Vpv2` and the DC-bus voltage; a `u16` tracking their product
is `Ppv`; a `u16` with no ARM-visible twin is `Ipv` (internal); and the `u8`
fields are per-channel **status / fault / mode** flags (and possibly a heatsink
temperature). A byte-exact record→register map can't be pinned from these two
images alone because the **DSP re-packs** the data between the MPPT's framing and
the ARM's `0x49` telemetry framing — that hop needs the C28x DSP image.

### Remote update path — the ARM is a `0x21/0x22/0x23` gateway

Does the ARM relay the firmware-update commands from the dongle? **Yes — the ARM
runs a dedicated firmware-update gateway task that accepts `0x21/0x22/0x23`
update frames and forwards them to the DSP link.** Recovered from the ARM
`ceaa-07xx` image:

- **Update task** — an endless 3-stage pipeline (`0x08028690` loop →
  `0x08028414` assemble, `0x08028234` manage, `0x0802782A` dispatch). At startup
  it loads the signature-tag registry (`SNEC SNED EDSN DPOT atez LAA1 SA22` at
  `0x08030550`) into its context `0x2000BF24`. `EDSN` is the same session tag the
  DSP bootloader validates on `0x21` (docs/05).
- **Command dispatch** (`0x080279CE`): reads the command from **`frame[1]`** (the
  Modbus function-code slot) and branches —

  | func | → handler | action |
  |---|---|---|
  | `0x21` / `0x31` | `0x080279F4` | session start — stashes image addr/len/CRC from the frame into RAM |
  | `0x22` / `0x32` | `0x08027D22` | program block |
  | `0x23` / `0x33` | `0x0802801A` | verify / commit |

  The `0x2x` and `0x3x` groups invoke the **same** handlers (two encodings — e.g.
  two targets or two origins — differentiated inside the handler; not fully
  resolved).
- **Forwards to the DSP link** — the dispatcher calls the USART3/DSP handler
  (`0x0801BA98`), references the DSP context (`0x2000AF60`) and reuses the DSP
  link's `0x321` length cap. It stages frames in a relay buffer (`0x2000B5F0`) and
  owns no UART base itself — it bridges assembled frames to the per-link helpers,
  the signature of a pass-through.

So the remote-update chain is **external tool → dongle (the ARM's external Modbus
port, UART5 / docs/08) → ARM update gateway (`0x21/0x22/0x23`) → DSP** — and,
because the MPPT sits *behind* the DSP (previous section), **updating the MPPT is
tunnelled one hop further: … → DSP → MPPT** (the MPPT bootloader's own
`0x21/0x22/0x23`, docs/13 above).

**Proven** (ARM image): the update task, its `0x21/0x22/0x23`(+`0x31/0x32/0x33`)
dispatch on `frame[1]`, the `EDSN` tag, and its coupling to the DSP link.
**Not fully traced:** a single store binding the relay buffer to the dongle UART
specifically (the input buffers are shared globals reached through link helpers,
and the dongle is the architecturally-/docs-indicated source rather than one I
followed instruction-by-instruction), which `0x2x` vs `0x3x` target is DSP vs
MPPT vs ARM-self, and the onward DSP→MPPT tunnel (needs the C28x image).

## Scope / what this means for the project

This image is **out of scope** for the current reimplementation, which targets
only the com MCU (see README). It does **not** belong in `include/inv/variant.h`:
that abstraction is for *models of the com MCU* (same silicon, same codebase), and
this is neither — a different core (M0+ vs M3) and a different role. It is better
understood as a new **peer processor** alongside the TI C2000 control DSP and the
com MCU — the EG4 platform splits firmware by role (`com` / `dsp` / `mppt`), and
this is the `mppt` one.

Open questions a schematic or a live unit would answer:
- Exact STM32G0 part number (and whether it's a clone, e.g. GD32).
- How many PV trackers this one MCU drives, and whether there is one such MCU per
  MPPT or one for all (the 12000XP/6000XP have 2 MPPTs, the 18kPV has 3).
- The exact frame layout and command set on the USART1 link — decoding the
  register map would let the com side (this project) read MPPT telemetry directly.
  It is very likely the same EG4 Modbus-family link as `docs/05-dsp-link.md`; a
  cross-check of the CRC seed and the `0x21/0x22/0x23` command bytes would confirm.

## DSP-side check (C28x images): the MPPT's `0x42` link is **not** in these DSP builds

The "MPPT ⇄ DSP" conclusion above is an **ARM-side inference** (the ARM has no
`0x42` path and no analog metering, so PV must arrive via the DSP). I now checked
it from the DSP side, against the two decoded C28x images — the 12000XP DSP
(`CEAA-xx07_dsp_vE_250325`, docs/07/10) and the 18kPV DSP
(`fAAB-xx22_Para375_20250428`, docs/15). **Neither DSP parses or emits the MPPT's
binary `0x42 0x01` frame.** So the specific CBAA `0x42` UART link is not present in
these builds; the picture needs refining.

What the DSP images actually show (direct reads):

- **No `0x42` MPPT frame handler, RX or TX.** The only `0x42` occurrences are an
  **ASCII console** where `'B'` (0x42) is one of ~16 single-char commands (SOF
  `0x7e`/`'Q'`, CR-terminated; `FUN_00096885`/`FUN_0009681f`), plus two payload
  writes and two flag assignments — none is a frame SOF or an MPPT poll.
- **The DSP meters analog itself.** It reads its own ADC result registers
  (ADC‑A `0xB00`/`0xB0A`, ADC‑C `0xB40`/`0xB54`, ADC‑D `0xB61`) and drives the
  power stage with ePWM (117 ePWM base loads). A C2000 controller sensing PV/grid/
  bus directly is the expected topology.
- **12000XP DSP:** only **SCI‑A/B**, bit-wise `0xA001` CRC, no spare link, no
  `0x42` → it does **not** use an external MPPT-over-UART. PV is sensed on-die.
- **18kPV DSP:** **SCI‑A/B/C**, **table-driven** CRC (the same Modicon-table
  family as the MPPT — no `0xA001`). Port roles:
  - **SCI‑B** — the ARM link (type-1 `0x49`/`0x41` + `0x21/0x22/0x23`; docs/10).
  - **SCI‑C** — a bidirectional inter-processor link (`FUN_0009EEFA`):
    RX frames start **`'T'` (0x54)**, TX frames start **`'D'` (0x44)**, 30-byte,
    CRC‑16 big-endian; each RX frame carries **~7 big-endian u16s + a status byte**
    into `DAT_000111C8…D2`, consumed by the DSP's **control loops**
    (`FUN_0009145D`/`FUN_00095779`), not forwarded verbatim to the ARM.
    **Update: this is the redundant / safety-CPU cross-check link, not the MPPT**
    — the DSP votes (median-of-3) and cross-checks these samples and gates
    operation on agreement + peer liveness (E027). See
    [`docs/29`](29-safety-cpu.md). (The CBAA MPPT's `0x42` framing appears on
    neither DSP.)
  - an **ASCII console** as above.
  None of these is the CBAA `0x42`/`0x01` framing.

### Interpretation (refines the ARM-side inference)

- For the **12000XP/18kPV**, the control DSP most plausibly **senses PV on its own
  ADCs**; the standalone **CBAA MPPT MCU is a separate product/config** (or pairs
  with a DSP build not on hand — note the version skew: MPPT image `…_250805`
  (Aug 2025) vs these DSP images Mar–Apr 2025). So "MPPT → DSP over the `0x42`
  UART" is **not evidenced** by the DSP images we have.
- The 18kPV DSP's **SCI‑C `'T'`/`'D'` link is a real inter-processor telemetry
  link** whose BE16 values feed the DSP control loops — a plausible **PV/MPPT or
  secondary power-stage sub-controller** by *shape*, but it uses a different SOF
  (`'T'`/`'D'`, not `0x42`) and a shorter 30-byte frame, so it **cannot be equated**
  with the CBAA MPPT without a matching DSP build or a live bus capture.

**Proven (direct reads):** no `0x42` handler in either DSP; DSP does its own ADC
metering; the 18kPV SCI‑C `'T'`/`'D'` sub-controller link and its field cluster.
**Open:** the positive identity of the SCI‑C peer, and which DSP build (if any)
actually terminates the CBAA MPPT's `0x42` link — both need a schematic or a live
capture.
