# Inter-processor / DSP link

Status: **framing decoded from the ARM side; physical UART→peer mapping pending
the schematic.** The TI C2000 DSP image is a **C28x** binary, which no tool in
this environment can disassemble, and its strings don't extract cleanly — so the
protocol was recovered from the ARM (fully disassemblable) and the DSP image
used only for corroboration.

> **Address note:** this doc was written before the `.hex` revealed the
> non-contiguous layout (see `docs/01`). Addresses in **segment 1**
> (`< 0x08002A00`) are correct as written — the comms parser `sub_080010ac`, the
> USART3 ISR `sub_08001316`, and RAM `0x20000028` are all here. Addresses quoted
> for **segment-2** functions (the per-UART handlers `0x0801a5ec`, `0x0801ac7c`,
> …) came from the raw `.bin`; add **`+0x2400`** for the true flash address.
> The *findings* (framing, field layout) are unaffected.

## Comms inventory (ARM side)

The ARM drives **five UARTs + SPI1 + CAN1**, through a shared stack:

| Peripheral | Evidence | Likely role |
|---|---|---|
| USART1/2/3, UART4, UART5 | shared init `sub_08001978`; per-UART ISR template | the 5 serial peers below |
| SPI1 | small transfer fn `sub_08000aca` (TXE-wait + send) | LCD or EEPROM |
| CAN1 | `sub_08003358`, 20-byte/entry table | parallel-unit / BMS (`ParaCANFault`) |

The five UART peers of an EG4 all-in-one are (some order): **DSP (control)**,
**BMS (lithium)**, **meter/CT**, **MPPT**, and the **external RS-485 dongle**
(the documented Modbus). The code confirms a common framing across them; only the
schematic says which MCU UART lands on which peer.

Each UART has the same ISR shape (confirmed for USART2 `sub_0801a5ec`, UART4
`sub_0801ac7c`, USART3 `sub_08001316`): check TXE IT (`0x727`) → TX next byte;
check RXNE (`0x20`) → `USART_ReceiveData` → per-UART byte state machine. Only
**USART3 is NVIC-vectored** (IRQ39); the others are serviced by polling their
flags, so USART3 is the most time-critical link.

## The framing: EG4 Modbus family (same as the external protocol)

Every link uses the EG4/Luxpower Modbus-family frame we already implemented
(`include/inv/modbus.h`): `addr func SN[10] <body> CRClo CRChi`, little-endian
fields. The USART3 byte-level parser (`sub_080010ac`, RX buffer at RAM
`0x20000028`, 800-byte window) was fully decoded:

- `[0]` address — accepted values **0 or 1** (resync if neither)
- `[1]` function — accepted set and resulting total frame length:

| func | meaning | frame length |
|---|---|---|
| `0x03` | read holding | 18 |
| `0x04` | read input | 18 |
| `0x06` | write single | 18 |
| `0x10` | write multiple | `body[16]` + 0x13  (byteCount + 19) |
| `0x21` | **undocumented** | 24 (10-byte payload) |
| `0x22` | **undocumented (bulk)** | `body[15] | body[16]<<8` + 0x13  (16-bit byteCount) |
| `0x23` | **undocumented** | 21; sub-type at `body[12]` (1/2 handled specially) |

- `[2..11]` SN[10]
- on a complete frame (`rxIndex == expectedLen`): set busy flag, set event bit
  `*(u16*)0x200004b8 |= 2` → main loop builds the response. TX is drained from a
  buffer at `0x20000028 + 0x321` by `sub_080012aa`.

### Buffer field map (RAM `0x20000028`, call it `rx`)
```
rx[0x000 .. 0x31F]  frame RX buffer (800 bytes)
rx[0x321 ..      ]  TX buffer
rx[0x336] u16       rxIndex
rx[0x338] u16       txIndex
rx[0x33A] u16       expected frame length
rx[0x33C] u16       TX length
rx[0x340] u8        frame-complete / busy flag
```

**This confirms the Modbus module** in `src/modbus/` against the real firmware:
address 0/1, the 0x03/0x04/0x06/0x10 set, the SN prefix, and the frame lengths
all match. The extended `0x21/0x22/0x23` are EG4-internal/undocumented commands
(candidates: time/SN set, bulk history/log read, firmware update) and are the
main thing still to decode.

## DSP image (C28x) — what we can and can't do

- 141,304 bytes, entropy ~6.5, **not encrypted/compressed** (tail is low-entropy data).
- Architecture is **TI C28x** — capstone/objdump/radare here can't disassemble it,
  and C28x's 16-bit `char` makes string extraction unreliable.
- Cross-ref with the ARM: only a weak shared marker `EDSN` (an SN-field fragment;
  ARM also has `SNEC`/`SNED`). No shared tokens — expected across architectures.
- Usefulness: confirms the DSP is openly analyzable *in principle*; to read it
  properly needs a C28x disassembler (Ghidra has a C28x/`TMS320C28x` processor
  module; TI's own tools also work).

> **Update:** the DSP image has now been disassembled — Ghidra 12.1.2 + the
> `outlandnish/ghidra-tms320c28x` SLEIGH module, ~650 functions recovered. Two
> findings matter here: (1) the image is **byte-swapped** (each 16-bit word is
> stored high-byte-first — see [`docs/07`](07-dsp-ac-first-mode.md) for the
> proof via `LCR` opcode counts), and (2) it is an **F2837x-class** part (flash
> at word `0x80000`; ePWM1–12 / 4× ADC / CLA). The "string extraction is
> unreliable" note is academic: the control image has **no** human-readable
> strings — the ARM-side Modbus map is the Rosetta stone. First decode target
> ("AC First" output-priority logic) written up in
> [`docs/07-dsp-ac-first-mode.md`](07-dsp-ac-first-mode.md).

## Comms stack & write-path (RE on the corrected image)

Traced from the USART3 frame-ready flag (`0x200004b8`) and the dispatchers:

- **Frames are validated, not blindly applied.** `sub_08001482` recomputes the
  CRC-16 (`sub_08000de4`) over the received bytes and compares it to the trailing
  CRC (`sub_08000d98`); only on match does it dispatch (`sub_08001420`). The
  byte parser also enforces **address ∈ {0,1}** and a **function-code whitelist**
  (`0x03/0x04/0x06/0x10` + undocumented `0x21/0x22/0x23`); anything else resyncs.
- **Tagged protocol, shared with the DSP.** `sub_08000896` selects a protocol
  mode by comparing a build-config word at flash `0x08031800` (`"NOTB"`) against
  `"UARB"` (`0x42524155`); handlers reference 4-char tags `SNEC`/`NOTB`/`SNFC`
  (`0x0800299c`). The DSP image contains `EDSN` — the same tagged family, a
  cross-reference that the two CPUs speak this protocol.
- **Firmware-update path found.** `sub_08000818` reprograms flash from
  `0x08005000` to `0x0807F800` in 0x100-byte pages and streams a `'P'` (0x50)
  progress byte — i.e. the "Programming" state / "Update" menu (IAP).
- **ARM owns the clock.** STM32 battery-backed RTC; validated calendar struct at
  RAM `0x2000a718` (`sec,min,hour,day,mon,year,dow`). "Set Time" sets this RTC.

**Open (needs schematic or a bus capture):** per-register *value-range*
validation on dongle writes was not found in the traced paths (frame-level
checks are present; value bounds may be delegated to the DSP / enforced by the
HMI's per-item min/max). And a byte-exact *DSP command frame* couldn't be pinned
by static RE alone. (The "which physical UART is the DSP vs the dongle" anchor is
no longer missing — DSP = USART3, dongle = UART5; see the Update note at the end
of this doc.) Best evidence still says: **ARM = timekeeper + config/HMI + bridge; the
DSP evaluates the real-time time-window rules** (the protocol's `0x10` = "SN +
time only" means time is explicitly pushed to whoever evaluates).

## Dynamic analysis (Unicorn harness: tools/emu.py)

A Unicorn emulator (`tools/emu.py`) runs firmware functions in a sandbox with
stubbed STM32 peripherals, capturing UART TX and tracing which named functions
execute. It is **validated**: `sub_08000d98(buf,len)` computes the Modbus CRC-16
correctly in-firmware (`CRC("123456789") == 0x4B37`), confirming the emulation
executes the real code faithfully.

What it established by injecting crafted Modbus frames into the USART3 buffer
(`0x20000028`) and running the processors:

- `sub_08001482` CRC-validates a frame (`sub_08000d98` compute vs `sub_08000de4`
  read-back) and dispatches via `sub_08001420` — but that path **only deep-processes
  the extended `0x21/0x22/0x23` commands**; standard `0x03/0x04/0x06/0x10` are
  no-ops there (empty response, no store). So USART3's `sub_08001482` path is the
  **tagged extended protocol** (the `SNEC/SNFC/...` records), *not* the standard
  register-serving Modbus.
- The standard register read/write (serving input/holding registers) is a
  **separate handler**, not yet pinned. The 356-byte block at RAM `0x20009048`
  (zeroed by the comms task) is the likely **input-register/telemetry array**;
  it is referenced by the USART2 handler (`sub_0801c9ec`) and the link parser
  `sub_08014a3a` (buffer `0x20007cec`), among others.

**Direction still unresolved.** The harness can answer it, but needs the right
entry points: run each link's service routine with a seeded register array and a
crafted request, and observe whether it (a) *responds* (slave: the master reads
the ARM's registers) or (b) *initiates* a write (master: ARM pushes to the DSP).
The blocker is matching each of the 5 links to its physical peer, which the
schematic settles directly.

## DSP side (C28x) — direction resolved, `0x21/0x22/0x23` placed

With the DSP now disassembled (Ghidra + `ghidra-tms320c28x`, see
[`docs/07`](07-dsp-ac-first-mode.md)) the link can be read from the **other end**,
which settles the open questions above without the schematic. The DSP's
master-facing serial link is **SCI-B**, and it runs the **same EG4 frame family
and the same CRC-16** as the ARM — the DSP's CRC routine `FUN_00081034`
(word `0x81034`) is the mechanical twin of the ARM's `sub_08000d98` (both
little-endian-reflected `0xA001`). That shared CRC is the anchor that proves the
two CPUs are on one wire. The link carries **two framings on the same transport**,
both `addr func … CRC16`, dispatched by the function/type byte `[1]`:

### 1. Firmware-update / bootloader path — uses `0x21/0x22/0x23`

The DSP bootloader `FUN_00080aa8` (word `0x80AA8`, in flash sector 0) is a
polled SCI-B receive loop that accepts **only** function codes
`0x21`/`0x22`/`0x23` — any other byte forces a resync. The frame lengths it
computes **match the ARM's extended table exactly**:

| code | DSP handling | length | matches ARM table |
|---|---|---|---|
| `0x21` | session start: validates the `"EDSN"` tag (`0x4E534445`) + SN fields, erases a flash sector | **24** | ✅ 24 |
| `0x22` | program a data block: sub-type `[14] ∈ {1,2}` (block-index → `0x80000+(n-1)*0x180`, or a direct 32-bit addr), writes flash in 8-word chunks via the RAM-resident flash API (`FUN_0000C47B`/`cb5d`) | **`byteCount + 0x13`** | ✅ bulk |
| `0x23` | verify / commit: compares stored vs received addr/len/CRC fields, sets "done" (state 3); sub-type `[12] ∈ {1,2}` | **21** | ✅ 21 |

Each command is **ACK'd** back to the ARM (`FUN_000810C5` TX). This is the
`"EDSN"` marker noted earlier in this doc (the DSP image's shared tag),
now explained: it is the DSP's SN-tag check on the update
handshake. **So yes — `0x21/0x22/0x23` are the DSP protocol's firmware-update
subset**, and they are driven by the ARM, matching the ARM-side finding that its
USART3 `sub_08001482` path only deep-processes exactly these three.

### 2. Runtime config/telemetry path — same frame family, type byte `1`

The application comms task `FUN_00098F72` (word `0x98F72`) receives frames into a
buffer at RAM `0x00AC80`, CRC-checks them with the same `FUN_00081034`, and on a
valid frame with type byte `[1] == 1` calls `FUN_0009E309 → FUN_00092EE2`, which
**unpacks the settings** (output priority `0x00ADA8` = Bat/PV/**AC First**, and
the rest of the `0x00AD??` config block) out of the received buffer into DSP RAM.
The config deserialiser is reached **only** from this receive path
(`FUN_00092EE2` has exactly one caller), and the task runs a **link-health state
flag** (`DAT_0000AD67` bit 2) driven by whether valid frames keep arriving. In the
other direction the DSP **builds and sends** a ~60-word telemetry frame
(`FUN_0009DD14`: fill `0x00ADC2` → append CRC-16 → transmit). The full layout of
this config push — frame envelope, the 8 settings blocks, and the proof that the
ARM streams *all* settings rather than deltas — is written up in
[`docs/08-arm-dsp-config-protocol.md`](08-arm-dsp-config-protocol.md).

### Direction: **ARM pushes, DSP is the slave**

Every config/control path on the DSP is **reactive**: it waits for an
ARM-initiated frame, validates CRC, and *applies* it (stores settings, programs
flash). The DSP never polls the ARM for configuration — it only consumes pushed
frames (and watchdogs their absence) and emits telemetry. So:

- **Config (incl. "AC First" output priority): ARM → DSP, pushed.** The ARM is
  timekeeper + config master exactly as hypothesised earlier in this doc;
  the DSP reads the pushed value and runs the real-time rules (see
  [`docs/07`](07-dsp-ac-first-mode.md)).
- **Firmware update: ARM → DSP, pushed** (`0x21/0x22/0x23`, DSP ACKs).
- **Telemetry: DSP → ARM.**

This resolves the "push vs pull" question from the DSP end. The one piece still
formally pending the schematic is the physical pin mapping ARM-USART3 ↔
DSP-SCI-B — but the byte-exact frame-length match, the shared CRC-16, and the
shared `"EDSN"`/`0x21-0x23` vocabulary make that pairing all but certain.

> **Update — the "DSP vs dongle" UART ambiguity raised throughout this doc is now
> resolved.** The ARM↔DSP link is **USART3** (SCI-B) and the external dongle is a
> **separate** link on **UART5** (`0x40005000`, handler `sub_0802afe2`): see
> [`docs/16`](16-arm-io-map.md) (pin/peer map), [`docs/08`](08-arm-dsp-config-protocol.md)
> (the UART5 dongle handler + the dual-mode ARM serializer), and
> [`docs/26`](26-dongle-firmware.md) (the dongle's own firmware — an RS-485
> half-duplex master datalogger — confirming it from the far end). So the ranked
> steps below that aimed to *pin* the DSP UART are largely answered; (2)'s
> data-flow trace landed on USART2 as the DSP→ARM telemetry writer (docs/22).

## How to finish (ranked)

1. **Schematic** (you're providing): label which MCU UART → DSP, BMS, meter,
   MPPT, dongle. That immediately pins the DSP link; then disassemble that UART's
   byte state machine + TX builder for its exact command/register set.
2. **Data-flow trace** (no schematic needed): find the Modbus read-input handler
   → the telemetry register array in RAM → whoever *writes* that array is the DSP
   link handler. This identifies the DSP UART from the ARM alone.
3. **Decode `0x21/0x22/0x23`** payloads from the USART3 dispatch (extends our
   Modbus engine to the full EG4 command set).
4. **C28x disassembly** of the DSP image in Ghidra to confirm the slave side.
