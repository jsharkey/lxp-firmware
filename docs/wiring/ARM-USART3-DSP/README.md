# ARM USART3 ↔ Control DSP (SCI-B)

**Authoritative** for this link. Research trail:
[`docs/05`](../../05-dsp-link.md) (link id + bootloader),
[`docs/08`](../../08-arm-dsp-config-protocol.md) (envelope + direction),
[`docs/10-dsp-config-field-map`](../../10-dsp-config-field-map.md) (per-block byte map),
[`docs/17`](../../17-dsp-frame-probe-handoff.md),
[`docs/22`](../../22-arm-dsp-core-split.md).

The inverter's internal control link: the ARM pushes the full configuration to
the DSP and streams it the clock; the DSP runs the real-time power FSM and sends
telemetry back. One wire carries two framings plus the firmware-update
bootloader.

> **Per-field surface:** [`fields.md`](fields.md) (in this directory) documents the
> individual block fields (one file per config block 0–8, plus the frame header,
> clock, `0x49` telemetry and `0x21/22/23` bootloader), mirroring the
> `docs/wiring/ARM-UART5-dongle/` tree. This wiring doc stays the transport/overview.

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **USART3** `0x40004800`, pins **PB10 TX / PB11 RX** | ✔ (ARM image) |
| TI C2000 Control DSP | **SCI-B** | ✔ (DSP image) |

The DSP end is SCI-B, proven from the disassembled DSP image: it is the DSP's
only ~19200 port (SCI-B `BRR 0xC2/0xC3`; SCI-A/C ≈ 9600), and the telemetry TX
path writes the SCI-B TXBUF pointer `DAT_0000aefe`. **Open:** the literal copper
pin-pairing is still schematic-level — the frame-length/CRC/vocabulary match
makes it all but certain.

## Physical

- **TTL inter-processor UART**, **19200 8N1** (USART3 `BRR 0x0c35`, APB1 60 MHz
  on this GD32F303-class clone). Not RS-485 (contrast USART2/UART4/UART5).
- Possible direction/enable line **PA0** (`sub_0801b560`, off the USART3 TX
  path) — **~ inferred**, not confirmed as a transceiver control.
- USART3 is the factory's only reliably NVIC-vectored UART (ISR IRQ39
  `sub_0801ba78`).

## Framing

All frames are EG4/Luxpower Modbus-family with **CRC-16/MODBUS** (poly `0xA001`,
init `0xFFFF`); the DSP's CRC `FUN_00081034` is the mechanical twin of the ARM's
`sub_08000d98`. Two framings share the wire:

**1. Type-1 block config** (the ARM→DSP config push; the DSP builds a `0x49`
telemetry mirror but the ARM does **not** consume it on USART3 — see
[`telemetry-0x49`](telemetry-0x49.md), corrected in T09):

```
off 0x00  SOF   : 0x41 ('A')  ARM->DSP        (DSP's 0x49 'I' mirror: not RX'd here)
off 0x01  type  : 0x01
off 0x02  0x00
off 0x03  len   : 0x36 (54)
off 0x04  ..0x13 fixed header (32-bit id/serial @0x05 BE, status/flags)
off 0x14  block id (rotated over the full config set)
off 0x15  block payload: big-endian fields  (per-block map: docs/10)
 ...      CRC-16 trailer
```

- **Big-endian, SN-less, block-tagged** — *not* register/value Modbus (that is
  the dongle channel, see [`ARM-UART5.md`](../ARM-UART5-dongle/README.md)). The discriminator is
  the block id at `0x14`, not a byte-count.
- Output priority is the single byte at frame offset `0x1E` of block 0.
- The ARM also streams the **clock** to the DSP (the DSP has no power-off RTC):
  a third frame from `0x20009754`, `0xA5 0xA5` preamble + y/m/d h:m:s
  (`sub_08021df8`).

**2. Firmware-update bootloader** — functions **`0x21` / `0x22` / `0x23`** only
(session-start/erase `"EDSN"`-tagged, program-block, verify/commit). The DSP
bootloader `FUN_00080aa8` (flash sector 0) accepts exactly these three and ACKs
each (`FUN_000810C5`). Lengths match the ARM's extended table exactly.

## Direction & roles

- **ARM pushes config, DSP is a reactive slave.** Config is sent ARM→DSP as a
  **full snapshot** (all blocks, continuously, scheduler-driven — not deltas, not
  edit-triggered). The DSP never polls the ARM for configuration.
- **The DSP polls the ARM as a Modbus slave on this wire.** The ARM's USART3 RX
  is a Modbus-slave (func `03/04/06/10`) + DSP-bootloader (`21/22/23`) demux
  (`sub_0801c6e0` → byte handler `sub_0801c3e6`, frame buffer `0x20007490`); it
  answers register reads/writes here. The harness uses this (`ModbusDsp`) as the
  factory register oracle.
- **The DSP's own `0x49` telemetry is NOT received by the ARM on USART3.** The
  demux rejects it; the ARM's telemetry comes from the **safety CPU** `0x49` on
  **USART2** instead. The DSP-side builder `FUN_0009DD14` → `FUN_0009D358` writes
  SCI-B TXBUF, but nothing on the ARM consumes it here. See
  [`telemetry-0x49`](telemetry-0x49.md) (T09 correction) and
  [`ARM-USART2`](../ARM-USART2-safety.md).
- Firmware update is ARM→DSP (`0x21/22/23`), DSP ACKs. The ARM also gateways MPPT
  updates through to the DSP — see [`MPPT-USART1.md`](../MPPT-USART1-DSP.md).

## Key functions

**ARM** (260214 App, base `0x08005000`): build wrapper `FUN_080273b4` (rotates
block id) → per-block builder `FUN_08026830` (`buf[0x14]=blockId`, BE @ `0x15`);
dual-mode serializer `sub_0803373c` (flag `0x2000aa0b` bit 0: 0=dongle LE+SN,
1=DSP BE block-tagged). **USART3 RX** (IRQ39 `sub_0801c774`): drain `sub_0801c6e0`
→ byte handler **`sub_0801c3e6`** (frame buffer `0x20007490`) — a Modbus-slave +
bootloader demux, **not** a `0x49` parser.
  - ⚠ `telemetry parser FUN_08025ab8(0x14)` and `type-1 RX SM FUN_0801bb0e` were
    previously listed here as USART3 — **they are the USART2 (safety-CPU) `0x49`
    path**, not USART3 (`FUN_08025ab8` reads the USART2 buffer `0x20009048`; the
    `0x49` SOF test is in the USART2 handler `sub_0801c808`). Corrected in T09 —
    see [`telemetry-0x49`](telemetry-0x49.md) and [`ARM-USART2`](../ARM-USART2-safety.md).
  - bootloader RX SM `FUN_0801bbe0` ([`bootloader-21_23`](bootloader-21_23.md)).

**DSP** (C28x, Ghidra + `ghidra-tms320c28x`): comms task `FUN_00098F72` (RX into
`0xAC80`, CRC, dispatch type 1) → `FUN_0009E309` → settings deserialiser
`FUN_00092EE2`; BE field readers `FUN_0009E7C2`/`FUN_0009E6BA`; CRC
`FUN_00081034`; telemetry TX `FUN_0009DD14`; bootloader `FUN_00080aa8`.

**Reimplementation:** [`include/inv/dsp_link.h`](../../../include/inv/dsp_link.h),
[`src/dsp/dsp_config.c`](../../../src/dsp/dsp_config.c),
[`src/dsp/dsp_link_port.c`](../../../src/dsp/dsp_link_port.c) (polled USART3 TX);
[`src/uart/uart3.c`](../../../src/uart/uart3.c) @ 19200 8N1. One block pushed per
~20 ms; full snapshot ~6×/s ([`src/main.c`](../../../src/main.c)). RX demux
(T09): [`src/dsp/dsp_rx.c`](../../../src/dsp/dsp_rx.c) +
[`src/dsp/dsp_rx_port.c`](../../../src/dsp/dsp_rx_port.c) — see
[`telemetry-0x49`](telemetry-0x49.md). Tests:
[`tests/test_dsp_config.c`](../../../tests/test_dsp_config.c),
[`tests/test_dsp_rx.c`](../../../tests/test_dsp_rx.c) +
[`tests/test_dsp_rx.py`](../../../tests/test_dsp_rx.py).

## Corrections folded in

- **Retracted:** "the ARM↔DSP link is standard Modbus (func-3 + SN, LE,
  `0x10+(reg-start)*2`)." That was the **dongle** path; forced in an early
  emulation that pinned the dual-mode serializer to dongle mode. The DSP gets
  BE, SN-less, block-tagged frames.
- Dongle-vs-DSP UART ambiguity resolved: **DSP = USART3, dongle = UART5**.
- `0x21/22/23` identified as the DSP bootloader/update subset (was "undocumented
  / time-or-SN set?").
- **T09:** retracted "the ARM parses the DSP `0x49` telemetry on USART3". The
  USART3 RX is a Modbus-slave + bootloader **demux** (`sub_0801c3e6`, buffer
  `0x20007490`) that rejects `0x49`; the `0x49` parse (`FUN_08025ab8`, buffer
  `0x20009048`, SOF test `sub_0801c808`) is the **USART2** safety-CPU path. See
  [`telemetry-0x49`](telemetry-0x49.md).

## Open

- Copper pin-pairing ARM-USART3 ↔ DSP-SCI-B (schematic).
- **Block count:** the DSP deserialiser handles **9 blocks (ids 0–8)**; our
  [`include/inv/dsp_link.h`](../../../include/inv/dsp_link.h) defines
  `DSP_CONFIG_NBLOCKS 8` (ids 0–7). Reconcile.
- The struct-field → register-number leg for the DSP RAM slot targets (regs
  64–89 group), still partly open (docs/10, docs/17).

## Factory RX buffer (ceaa-07xx)

Per-frame linear RX buffer **800 B** at `0x2000a304` (`sub_0801b6be`, guard
`cmp #0x320`), inside a ~1113 B struct. Our `src/uart/uart3.c` uses a 256 B ring
— ample for the ~54 B config frames while streaming, but it can't hold an
800 B frame whole. Sizing + verdict: [`docs/47`](../../47-factory-ram-static-breakdown.md).
