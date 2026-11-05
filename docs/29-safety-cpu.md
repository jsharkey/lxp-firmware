# The redundant / "safety" CPU — concrete evidence

The EG4 platform is a **three-processor** system (README, docs/01): the Control
DSP (TI C2000), the Com/HMI MCU (STM32, this project), and a third **redundant /
"safety" CPU**. Until now the safety CPU was only a label. This note collects the
first concrete, firmware-level evidence of **what it is, where it connects, and
what it does** — most of it read directly from the DSP image.

## What it is (protocol level — already established)

| anchor | where | says |
|---|---|---|
| `Slave Ver` version register | `HR_SLAVE_COM_VER = 9` (`modbus_map.h`), docs/01 | reg 9 **low byte = redundant CPU firmware version** (high = com MCU) — so it is a *versioned MCU* the system queries |
| fault **E027** | `FAULT_CPU_SAMPLE_MISMATCH = 27` (`faults.h`) | **"Main vs redundant CPU sample mismatch"** — two CPUs sample the same quantities and must agree |
| three-CPU table | docs/01 | `Cntl Ver` = DSP, `Com Ver` = STM32, **`Slave Ver` = redundant/safety CPU (cross-checks sampling)** |

So by spec the safety CPU is a **redundant sampler**: it independently measures the
safety-critical quantities, the two CPUs are cross-checked, and a mismatch raises
E027. This is the standard dual-redundant grid-protection pattern (anti-islanding /
independent over-/under-V/F trip) that grid codes require.

## Where it connects — the DSP ↔ safety-CPU link (SCI-C), proven from the DSP

On the **18kPV DSP** (`fAAB…`) there is a dedicated inter-processor serial link
that behaves exactly like a redundant-sampling peer. It is **SCI-C** — the third
SCI, distinct from SCI-B (the ARM link, docs/23) — at **~9600 baud**
(`SCIC_SCILBAUD=0x86`, vs SCI-B's 19200).

**The link** (`FUN_0009EEFA`): the DSP **receives** frames with SOF **`'T'`
(0x54)** — 30 bytes, CRC-16 big-endian over 28 — carrying **~7 big-endian u16
samples + a status byte** (into `DAT_000111C8…D2`), and **transmits** a short
**`'D'` (0x44)** command/mode frame back. So the DSP is the master of a
bidirectional sample/command exchange with this peer.

**The cross-check (the decisive evidence):**

- **Voting primitives.** `FUN_0009DFFD` / `FUN_0009DFE6` are **median / middle-of-
  three selectors** — the canonical redundancy/voting operation. The received
  samples are run through them.
- **Agreement check with debounce.** `FUN_0009EE09` computes the **absolute
  difference** of two of the voted values and compares it to a tolerance
  (`abs(a-b)` vs `200` / `0x96`), against grid-window limits
  (`DAT_0001120C`, `DAT_0001216B` — model-set to values like `0x2D0`/`0x30C`,
  `0x4B0`/`0x514`, `900`), with a 5–6 tick debounce. On persistent disagreement it
  **sets a protection bit**, `DAT_00012318` bit **`0x200`**.
- **Comms-loss is a fault too.** When the `'T'` link stops delivering valid frames,
  `FUN_0009EEFA` sets `DAT_00012318` bit **`0x20000`**.
- **The result gates the inverter.** `FUN_00098507` returns "run OK" **only if**
  the cross-check bits are clear (`DAT_00012318 & 0x200`, `& 0x2000`, sign bit all
  0); a set disagreement or comms-loss bit makes it return "inhibit." I.e. **a
  main-vs-peer sample mismatch, or loss of the peer, trips protection** — exactly
  the E027 behaviour.

That combination — an independent CPU feeding redundant samples, median voting, an
abs-difference agreement check, and operation gated on agreement + peer liveness —
is a **safety/redundant sampling channel**, not telemetry, MPPT, or a dongle.
(This supersedes the tentative "SCI-C = PV/MPPT sub-controller" guess in docs/13:
the `'T'`/`'D'` peer is the safety CPU.)

## Where it connects — the ARM side (USART2), **PROVEN** (docs/30)

The ARM reaches the safety CPU on **USART2** (19200, RS-485, DE on PC2). This was the
"strong inference" in an earlier draft; [`docs/30`](30-safety-cpu-arm-handoff.md) then
**proved it from the ARM image** by showing the ARM *reports* the cross-check status
straight out of the USART2 frame rather than computing it:

- **E027 is copied from the USART2 frame.** The Modbus fault word (`IR_FAULTCODE_L/H`,
  served from `STATUS 0x2000a0d8+0x88`) is taken **verbatim from `BANK+0xd0`**, a
  **big-endian u32 at USART2 frame offset `+5`** (parser `sub_08024d74`, classifier
  `sub_0801b480`), with only the two internal-comm bits (E000, E017) overridden
  locally. **bit 27 = `FAULT_CPU_SAMPLE_MISMATCH`** is not one of those, so it is the
  frame's own bit — the ARM never diffs two sources to raise 27; it trusts the word
  the USART2 peer sends. That peer is therefore the CPU running the cross-check = this
  safety CPU.
- **Grid-domain warnings and the peer version arrive on USART2.** The WARN word
  (`STATUS+0x8c`, reg 62/63) takes bits 10..31 from `BANK+0xd4` = the USART2 frame `+9`
  status dword, so the grid warnings (`W016/W017/W018`) are reported from the peer; its
  low bits (incl. `W008 FW-version-mismatch`) are ARM-computed locally. The peer's
  Control-CPU (DSP) **version** byte is `BANK+2` of the frame (docs/32); the identity
  bytes `BANK+2..6,+8` are received on USART2 and preserved across a bank reset.
- **Peer liveness is a USART2 property.** The USART2 driver `sub_080259d8` tracks link
  health (`0x2000a6c4`, fail-counters `0x20009048+6`); the classifier asserts the
  **comms-loss bit `0x20000`** (E017) of the fault word `STATUS+0x88` from that local
  tracker — the ARM-side twin of the DSP's `0x20000`.
- USART2 is **19200, RS-485** — electrically distinct from the DSP's TTL SCI-B,
  consistent with a separate MCU; and docs/23 proved USART2 is **not** a DSP SCI.

So the topology is now pinned on both ends: a safety CPU that **cross-checks the DSP
over SCI-C (9600)** and **reports to the ARM over USART2 (19200 RS-485)**, supplying
the validated grid/mode telemetry the ARM classifies plus its agreement (E027) /
version (W008) status:

```
DSP (C2000) —SCI-C 9600 'T'/'D'— safety CPU —USART2 19200 RS-485— ARM (STM32)
```

The SCI-C↔USART2 pairing of the *same physical MCU* remains role-level inference (two
links, same peer by behaviour); a schematic (or the peer's part number) is the last
unresolved detail.

## Role (synthesis)

- **Independent, redundant sampling** of the safety-critical quantities — grid
  voltage/frequency windows (the `0x2D0/0x30C/0x4B0/0x514/900` thresholds), i.e.
  the anti-islanding / grid-protection set.
- **Cross-check against the DSP ("main").** Median voting + abs-difference with
  debounce; sustained disagreement ⇒ protection bit ⇒ **E027**.
- **A safety interlock, not just a monitor.** Its agreement (and liveness) **gate
  whether the DSP will run** (`FUN_00098507`) — losing the peer or disagreeing
  inhibits the inverter. This is the defining property of a safety CPU.

## Confidence & open items

- **Proven (direct DSP reads):** the SCI-C `'T'`/`'D'` link; the median/voting
  functions; the abs-difference agreement check with debounce; the protection
  status bits (`0x200` mismatch, `0x20000` comms-loss) and the run-gate that
  consumes them. This is a redundant-sampling safety channel on the 18kPV DSP.
- **Proven (direct ARM reads, docs/30):** that the ARM reaches this peer on
  **USART2** — E027 (fault bit 27) and W008 (version mismatch) are *reported* out of
  the USART2 frame, and peer comms-loss is tracked on the USART2 link. The
  `Slave Ver`/E027 "redundant CPU" of the protocol **is** the USART2 peer.
- **Strong inference:** that the USART2 peer and the DSP's SCI-C `'T'`/`'D'` peer are
  the *same physical MCU* (same role, same `0x200`/`0x20000` status semantics on both
  links) — not separately provable from firmware alone.
- **Open:** the safety CPU's part/identity (not derivable from these images); the
  exact physical quantities in the 7-value `'T'` record (grid V/F vs other); and
  the **12000XP** arrangement — it has only SCI-A/B, its SCI-A carries a *different*
  bulk `LS4_RAM` stream (not a `'T'`/`'D'` cross-check), so whether the smaller
  model has an external safety CPU or folds the redundancy in differently is
  unresolved (E027 lives in the 18kPV-superset map).

> **Next (ARM side):** [`docs/30`](30-safety-cpu-arm-handoff.md) hands the ARM agent
> the precise leads — the `Slave Ver` (reg 9 low byte) source and the E027 raise
> point — to confirm whether **USART2 ⇔ safety CPU** (pinning it on both ends) or
> the DSP merely relays its version/status.
