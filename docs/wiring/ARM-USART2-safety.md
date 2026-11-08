# ARM USART2 ↔ redundant / "safety" CPU

**Authoritative** for this link. Research trail:
[`docs/30`](../30-safety-cpu-arm-handoff.md) (ARM-side resolution — primary),
[`docs/29`](../29-safety-cpu.md) (DSP/safety-CPU side),
[`docs/22`](../22-arm-dsp-core-split.md) (ARM/DSP split),
[`docs/23`](../23-dsp-sci-a-crosscheck-handoff.md) (why it is *not* a DSP SCI),
[`docs/32`](../32-firmware-version-registers.md) (version byte),
[`docs/33`](../33-usart2-telemetry-bank.md) (full bank field map + dongle-register sweep).

This is the ARM's **primary telemetry input**: the operating mode it classifies,
its core input registers, its fault word and the inverter's version registers
are all built from the frame arriving here. The peer is the redundant/safety
CPU, which sits between the DSP and the ARM.

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **USART2** `0x40004400`, pins **PA2 TX / PA3 RX** | ✔ (ARM image) |
| redundant / "safety" CPU | *(its port/part unknown)* | ✔ peer *role* pinned from the ARM side |

The peer is **not** a DSP SCI (refuted in docs/23 — the DSP has only one 19200
port, SCI-B, already = USART3) and the data is **not** DSP-relayed verbatim (see
below). The safety CPU's part number is not derivable from the images.

## Physical

- **RS-485, 19200 8N1**, **RX-only** this boot (RXNEIE; `BRR 0x0c35`).
- Direction/DE on **PC2** (`sub_0801bde4`, adjacent to the USART2 driver).
- ISR IRQ38 `sub_0801bddc`; validated frames parsed by `sub_080259d8`
  (CRC `sub_08014bec`), length gate ≥ `0x54`.

## Framing

EG4 Modbus-family, **type-1**, **big-endian** multi-byte fields, CRC-16/MODBUS.
Decoded into the telemetry bank at **`0x20009e54`** (served as Modbus input
registers by `sub_0803289c`). Notable bank offsets (relative to `BANK`):

| field | bank offset | dongle reg | notes |
|---|---|---|---|
| operating-mode byte | `+0x00` (frame `+4`) | IR 0 `STATE` | **the one DSP-originated field**; relayed by the safety CPU, classified into IR_STATE by `sub_0801b480` |
| Control-CPU (DSP) version | `+0x02` (= `0x20009e56`) | HR 10 low | relayed ([`docs/32`](../32-firmware-version-registers.md)) |
| grid voltage R / S / T | `+0x20 / +0x28 / +0xb6` | IR 12 / 13 / 14 | safety CPU's **own** measurement |
| grid frequency | `+0x5e` | IR 15 | safety CPU's own |
| PV1 / PV2 voltage | `+0x4c / +0x4e` | IR 1 / 2 | safety CPU's own |
| radiator temp 1 / 2 | `+0x1e / +0x1c` | IR 65 / 66 | safety CPU's own |
| **fault** bitfield | `+0xd0` (frame `+5`) | IR 60/61 (via `STATUS+0x88`) | **E027 = bit 27** (frame's own bit); bits 0/17 (E000/E017) set locally |
| **warn** bitfield | `+0xd4` (frame `+9`) | IR 62/63 (via `STATUS+0x8c`) | grid warns `W016/17/18` from the frame (bits 10-31); bits 0-9 incl. **W008** are ARM-computed |

Full field map + dongle-register sweep: [`docs/33`](../33-usart2-telemetry-bank.md).

## Direction & roles

**safety CPU → ARM.** The ARM *reports*, does not compute, the status carried in
the frame (the classifier `sub_0801b480` merges each status word with the
ARM-local accumulator `0x2000a6c4`):

- **E027** (FAULT_CPU_SAMPLE_MISMATCH) — the **fault** bitfield at `BANK+0xd0`
  (frame `+5`, BE u32) → `STATUS(0x2000a0d8)+0x88` → IR 60/61. E027 (bit 27) is
  the frame's own bit; only E000 (bit 0) and E017 (bit 17) are set locally.
  Parser `sub_08024d74`.
- **Grid warnings** `W016/17/18` — the **warn** bitfield at `BANK+0xd4`
  (frame `+9`) → `STATUS+0x8c` → IR 62/63 (bits 10-31 from the frame).
  **W008** (FW-version mismatch) is **ARM-computed** (a low bit from the version
  compare), *not* carried in the frame.
- **Peer liveness** — comms-loss bit `0x20000` driven by the USART2 driver's own
  health tracker (`0x2000a6c4`, fail-counters `0x20009048+6`).

> **Fault/warn order (corrected per [`docs/33`](../33-usart2-telemetry-bank.md)).**
> Earlier drafts (docs/30) swapped the two: the **fault** word is `BANK+0xd0` →
> `STATUS+0x88`, the **warn** word is `BANK+0xd4` → `STATUS+0x8c`. W008 is derived
> locally, not relayed.

The safety CPU is an **independent redundant sampler** that median-votes grid
V/F against the DSP, checks agreement with the DSP's samples (over
[`DSP-SCI-C.md`](DSP-SCI-C-safety.md)), and **gates whether the DSP is allowed to run**.
It is a safety interlock, not a passive monitor.

## Corrections folded in

- **The measured values here are the safety CPU's own, not DSP-relayed**
  (commit `896f4aa`). Only the mode byte (`BANK+0`) is DSP-originated.
  **Trap:** [`docs/22`](../22-arm-dsp-core-split.md)'s table cell still prints
  "PV1/PV2 voltage = **DSP telemetry, verbatim** … (USART2 bank)"; that cell was
  annotated-but-not-edited. This doc is the corrected source.
- First read as the DSP's 2nd SCI (docs/22) → corrected to "relayed, not a
  direct DSP SCI" (docs/23) → pinned as the **safety CPU** from the ARM side
  (docs/30).

## Open

- Whether the safety CPU's SCI-C peer (DSP side) and this USART2 peer are the
  **same physical MCU** — role-level **~ inferred** (same `0x200`/`0x20000`
  status semantics on both links), not firmware-provable.
- Safety CPU part number.
- Whether the safety CPU self-measures PV/grid or shares the DSP's sense lines.
- 12000XP (`ceaa`) leaves the redundant-CPU version field at 0 and may fold
  redundancy differently from the 18kPV (`fAAB`); the 12000XP external-safety-CPU
  arrangement is not fully resolved.

## Factory RX buffer (ceaa-07xx)

Per-frame linear RX buffer **64 B** at `0x2000af60` (`sub_0801bb0e`, guard
`cmp #0x40`; SOF byte `0x49` 'I'), inside a ~875 B struct with the decoded
telemetry. Ours `src/uart/uart2.c` uses a 256 B ring. See [`docs/47`](../47-factory-ram-static-breakdown.md).
