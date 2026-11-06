# DSP SCI-C ↔ redundant / "safety" CPU

**Authoritative** for this link. Research trail:
[`docs/29`](../29-safety-cpu.md) (primary),
[`docs/30`](../30-safety-cpu-arm-handoff.md) (the ARM-side consequence).

The DSP's redundant-safety cross-check link. The DSP exchanges its raw samples
with the safety CPU; the safety CPU votes, checks agreement, and **gates whether
the DSP is allowed to run**. The safety CPU then reports the consolidated result
to the ARM over [`ARM-USART2.md`](ARM-USART2-safety.md).

## Endpoints

| end | port | confidence |
|---|---|---|
| TI C2000 Control DSP | **SCI-C** (`SCIC_SCILBAUD = 0x86`) | ✔ (DSP image) |
| redundant / "safety" CPU | *(its port/part unknown)* | ✔ link proven DSP-side |

Distinct from SCI-B (the ARM link, ~19200) — SCI-C runs ~9600. This is **not**
SCI-A (an unrelated bulk dump — see [`DSP-SCI-A.md`](DSP-SCI-A-open.md)).

## Physical

- **TTL, ~9600 baud** (TTL SCI, not RS-485 — electrically distinct from the
  ARM's RS-485 USART2).

## Framing — `'T'` / `'D'`

Link driver `FUN_0009EEFA`. Bidirectional:

- **DSP receives** frames with SOF **`'T'` (0x54)** — 30 bytes, CRC-16
  big-endian over the first 28 — carrying **~7 big-endian u16 samples + a status
  byte** (into `DAT_000111C8…D2`).
- **DSP transmits** a short **`'D'` (0x44)** command/mode frame back:
  `[1] = DSP working-state byte (DAT_0001230E)`, `[2] = (DAT_00011205 & 0xC) >> 2`.
  **No grid/PV/frequency is sent over SCI-C** — only a state byte + a 2-bit flag.

## Direction & roles

DSP is the master of a bidirectional sample/command exchange. The safety CPU:

- independently samples grid V/F safety windows (thresholds `0x2D0/0x30C/0x4B0/
  0x514/900`);
- median-of-3 votes (`FUN_0009DFFD`/`FUN_0009DFE6`);
- runs an abs-difference agreement check with debounce (`FUN_0009EE09`,
  `abs(a-b)` vs `0x96`);
- sets protection bit `DAT_00012318` `0x200` on disagreement, `0x20000` on
  comms-loss;
- gates the run-enable (`FUN_00098507` returns run-OK only if those bits clear).

Those `0x200` / `0x20000` semantics are exactly what the ARM reports as **E027**
(sample mismatch) and the peer comms-loss bit on USART2 — the link between the
two wires that makes the "same safety CPU" inference strong.

## Corrections folded in

- Supersedes the old `docs/13` guess "SCI-C = PV/MPPT sub-controller."
- On the 18kPV (`fAAB`), SCI-A is init-only/idle; the DSP↔safety-CPU link is
  SCI-C only.

## Open

- That this SCI-C peer and the ARM's USART2 peer are the **same physical MCU** is
  **~ inferred** (shared status semantics), not firmware-provable.
- Safety CPU part number.
