# Firmware analysis — ARM "com" processor

This is the reverse-engineering baseline for the **communications / HMI / supervisor**
MCU (the file named `..._com_vE_250325.bin`). Everything here was derived
directly from the shipped binary; nothing is guessed from a datasheet alone.
Where a fact is an inference rather than a direct read, it is marked *(inferred)*.

> **Image version.** This is the original analysis of the **05-series** 12000XP
> image (`..._com_vE_250325.bin`, 244,080 bytes, monolithic, vectors
> `@0x08000000`). The project's **current working reference is the 07-series**
> `ceaa-07xx_vE_260214` (App over a bootloader, vectors `@0x08005000`), whose app
> addresses do **not** match this image's. Treat the specific addresses below as
> 05-series; for the current IO map / links / registers see
> [`docs/16`](16-arm-io-map.md), [`docs/wiring/`](wiring/README.md) and
> [`docs/modbus-dongle/`](modbus-dongle/README.md), and
> [`docs/11`](11-12000xp-revisions.md) for the 05→07 delta.

## Image facts (direct reads)

| Property | Value | How we know |
|---|---|---|
| Size | 244,080 bytes (0x3B970) | file length |
| Load / base address | `0x08000000` | STM32 flash alias; `SystemInit` writes `SCB->VTOR = 0x08000000` |
| RAM base | `0x20000000` | initial SP + data pointers |
| Initial SP | `0x200008D0` | vector[0] |
| Reset handler | `0x08002980` | vector[1] |
| Encryption / compression | **None** | entropy ≈ 6.6 across the whole image, no high-entropy blocks |
| Vector table | at `0x08000000`, 16 system + 60 external = 76 entries | parsed |

The "no encryption" result is the important one: **every byte is readable and
disassemblable**, so a reimplementation is technically feasible.

## CRITICAL: the `.bin` is non-contiguous — use the `.hex`

The raw `.bin` dump is a **concatenation of non-contiguous flash regions with
the gaps removed**, so a byte offset in the `.bin` does **not** equal
`flash_addr - 0x08000000`. The Intel-HEX of the same firmware gives the true
addresses. Real flash layout (512 KB part, `0x08000000`–`0x08080000`):

| true flash range | size | contents |
|---|---|---|
| `0x08000000`–`0x080029FF` | 10.7 KB | vector table + early code/startup |
| *gap* `0x08002A00`–`0x08004DFF` | ~9 KB | unused/reserved (0xFF) |
| `0x08004E00`–`0x0803031D` | 173 KB | main code |
| *gap* `0x0803031E`–`0x0803151D` | ~4.5 KB | unused/reserved (0xFF) |
| `0x0803151E`–`0x0803EF67` | 55 KB | code + **HMI string tables** |
| `0x08040000` (4 B), `0x0807F7FC` (4 B) | — | markers (`SNEC` sits at the top) |

Consequence: everything past `.bin` offset `0x2A00` was mis-addressed by
`+0x2400` (after gap 1) or `+0x3600` (after gap 2). This is why HMI strings
appeared "unreferenced" earlier — the code's pointer/literal references use the
*true* addresses, which didn't match the shifted ones. **All RE must run against
the correctly-addressed flat image**: `tools/hex2bin.py firmware.hex flat.bin`
(fills gaps with 0xFF, every byte at its true address). Segment-1 analysis
(vectors, `SystemInit` @0x0800231c, the comms parser @0x080010ac) was already
correct because it lives below the first gap.

## Product identification: EG4 12000XP

**The firmware binary is the EG4 12000XP** com MCU (per the maintainer). The
supplied Modbus document is the **EG4 18kPV-12LV** spec, which uses the **same
protocol** — the 12000XP is a closely related, **non-hybrid** variant, so some
registers/features are present in the map but unused on this device:

- **2 MPPTs only** → `Vpv3`/`Ppv3`/`Epv3*` registers are unused.
- Hybrid grid-tie features (e.g. export-to-grid, AC-couple) are not applicable.

The firmware appears to be a **shared com-MCU codebase** across EG4 models
(hybrid-related HMI strings are present in the binary), with the active variant
selected at runtime by the **`Model`/`Com Addr` settings** — so the presence of
a string or register does not imply the feature is enabled on the 12000XP.
Treat the 18kPV map as a **superset**.

The system has **three processors**, each with a firmware-version byte in the Modbus
map (HR 9/10). Where each byte actually comes from is traced in
[`docs/32`](32-firmware-version-registers.md):

| Modbus version field | reg · byte | Role | This project? | ARM-side source |
|---|---|---|---|---|
| `Cntl Ver` (Control CPU) | 10 · low | TI C2000 DSP (power stage, MPPT, PWM, grid sync) | no | USART2 bank `+2` — the DSP's version **relayed via the safety CPU** (docs/30/31) |
| `Com Ver` (Communication CPU) | 9 · high | **Communication/HMI MCU — this STM32F103** | **yes** | constant `0x05` (the ARM's own baked-in version) |
| `Slave Ver` (Redundant CPU) | 9 · low | Redundant/safety CPU (cross-checks sampling; fault E027) | no | constant `0x00` — *not populated* in the 12000XP `ceaa` image |
| `FW version code` | 10 · high | — (ARM build/protocol code, not a CPU) | — | constant `0x01` |

## MCU identification: STM32F1-compatible, **M4-class core** (GD32F303-style clone)

> **Correction (dynamic RE, see [`docs/19`](19-gpio-test-harness.md)).** This was
> first read as a Cortex-**M3** STM32F103. It is an **STM32F1-*compatible*** part
> but the core is **ARMv7E-M (M4-class), not M3**: the factory image executes DSP
> instructions (`smlabb`, `sdiv`) as live code, which are **undefined on
> Cortex-M3** (they fault under an M3 model and run under M4). An F1
> peripheral/pin map + an M4 core points to a **GD32F303-series** clone (EG4 uses
> cost-reduced ST-compatible parts). Our own firmware builds `-mcpu=cortex-m3`
> and still runs — M3 is a subset of M4 — but the silicon is M4-class.

Evidence, in decreasing strength:

1. **DSP/`sdiv` instructions in executed code** (`smlabb`, `sdiv`, …): present on
   ARMv7E-M (Cortex-M4), **undefined on Cortex-M3**. Decisive for the core.
2. **Peripheral bases in literal pools**: `RCC @ 0x40021000` and
   `FLASH_ACR @ 0x40022000`. These addresses are the **STM32F1** layout
   (on ST F2/F4 they are `0x40023800` / `0x40023C00`) — i.e. F1-*compatible*
   peripherals, which GD32F303 (an M4 core) also uses.
3. **Fault vectors present**: MemManage / BusFault / UsageFault are populated,
   ruling out Cortex-M0/M0+.
4. **60 external IRQs** — matches the STM32F1 high-density interrupt map.
5. **`SystemInit`** is textbook CMSIS-F1: enable HSION, clear `RCC->CFGR`,
   disable HSE/CSS/PLL, set `RCC->CIR`, call `SetSysClock` (HSE+PLL), set VTOR.

Filename hint `vE` is consistent with an STM32F103**VE** (512 KB flash,
LQFP100). **To confirm the exact part (flash/RAM size, package), please supply
the real part number — you are the maintainer and already know it.** The used
image (238 KB) fits a 256 KB part but the `V`/`E` hint points to 512 KB.

## Original build toolchain: Keil MDK (ARM Compiler / armcc) *(inferred, high confidence)*

The C startup uses ARM-Compiler **scatter-loading** (`__scatterload`, the
`nop.w; nop.w; bl __scatterload; … ; b.w .` idiom), not the GCC
`_sdata/_edata/_sbss/_ebss` copy loop. This matters:

- The original `.data`/`.bss` layout is driven by a **scatter file**, not a
  GCC linker script.
- Our reimplementation will use **`arm-none-eabi-gcc`** with our own linker
  script. The result will be **functionally** equivalent, **not** byte-identical.
  (Byte-identical would require reproducing armcc + its scatter file — possible
  but not worth it for a project whose goal is contributable features.)

## Peripherals actually used

Interrupt usage is sparse — the board is mostly **polled**:

| Vector | Handler | Meaning |
|---|---|---|
| SysTick | `0x080018A5` | system timebase |
| PVD (IRQ1) | `0x080028A0` | programmable voltage detector (brown-out / power-fail save) |
| USART3 (IRQ39) | `0x08002898` | serial comms (RX) — **now confirmed the ARM↔DSP (SCI-B) link**; the external RS-485 dongle is a *separate* port, UART5 (see docs/16, docs/25, docs/26) |
| all other 58 IRQs | `0x080029A8` | shared default handler (`b.w .`) |

Peripheral literal references (USART1/2/3, GPIO ports, ADC, timers, etc.) also
appear but gated behind polling. A full, verified peripheral map is tracked in
`docs/03-peripheral-map.md` (TODO — recursive disassembly pass).

## Role of this processor

The strings make the division of labor unambiguous. This ARM MCU is **not** the
power-electronics controller — that's the TI C2000 DSP. This chip is the
**system supervisor + human interface + communications**:

- **LCD + keypad HMI** (ENTER/ESC/UP/DOWN; "LCD Ageing Test", "KEY Ageing Test";
  bitmap font tables occupy a large part of flash — the repeated `III…` runs).
- **Settings store & menu** (battery setup, charge/discharge limits, AC-charge
  windows, AC-couple, generator charge, grid/CT config, EPS V/F, model, time).
- **Operating-mode state machine** (PVGridOn, PVCharge, BatGridOn, ACCharge,
  Bypass, …, all the `*GridOn/*GridOff` combinations).
- **Fault aggregation & display** (see `include/inv/faults.h`).
- **Grid metering** (CT ratio 1000/2000/3000:1, import today/total, L1N/L2N).
- **Parallel operation** over CAN (`ParaCANFault`, "Parallel Setting").
- **Firmware update** ("Update" menu — likely an IAP path).

The real-time control loop (PWM, current regulation, MPPT algorithm, grid sync)
lives in the DSP and is explicitly out of scope.

## System topology *(inferred)*

```
        PV1 ─┐                                   ┌─ Grid L1/L2/N  (metered via CT)
        PV2 ─┤      ┌───────────────┐            │
             ├─────▶│  TI C2000 DSP │◀── CAN/UART ─┐
     Battery ─┤      │ (power stage, │            │ │
             │      │  MPPT, PWM,   │            │ │   ┌──────────────┐
    EPS out ─┘      │  grid sync)   │            └─┼──▶│ STM32F103 ARM│──▶ LCD + keys
                    └───────────────┘    this file → │ (HMI/comms/   │──▶ RS485/CAN
                                                      │  supervisor)  │    (Modbus? parallel)
                                                      └──────────────┘
```

The exact ARM↔DSP link (USART3? CAN? both?) and its message format are the
**single most valuable thing to document next** — it is the hard interface our
reimplementation must honor, and it cannot be fully recovered from the ARM
binary alone without either (a) the protocol spec, or (b) a bus capture.

> **Resolved since:** the ARM↔DSP link is **USART3** (DSP SCI-B — shared CRC-16,
> `0x21/0x22/0x23` bootloader, config push), with DSP→ARM telemetry on **USART2**;
> the external RS-485 **dongle** is a distinct link on **UART5**. See
> [`docs/05`](05-dsp-link.md), [`docs/08`](08-arm-dsp-config-protocol.md),
> [`docs/16`](16-arm-io-map.md), and [`docs/26`](26-dongle-firmware.md).
