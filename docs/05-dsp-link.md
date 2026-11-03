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
by static RE alone — which physical UART is the DSP vs the dongle is the missing
anchor. Best evidence still says: **ARM = timekeeper + config/HMI + bridge; the
DSP evaluates the real-time time-window rules** (the protocol's `0x10` = "SN +
time only" means time is explicitly pushed to whoever evaluates).

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
