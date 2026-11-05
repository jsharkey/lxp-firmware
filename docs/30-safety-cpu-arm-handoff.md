# Hand-off to the ARM agent: pin the safety CPU via `Slave Ver` (reg 9) + E027

**For the ARM-side agent** (you have the factory ARM image). The DSP side has now
found the redundant / "safety" CPU firsthand — see [`docs/29`](29-safety-cpu.md). One
link remains to pin from the ARM end: **is the ARM's USART2 peer that same safety
CPU?** Two ARM-side artifacts settle it, and you're closest to both.

## What the DSP side established (so you know what to match)

- The **18kPV DSP** runs a redundant-sample cross-check with a peer on **SCI-C**
  (~9600, separate from the ARM's SCI-B): it receives `'T'` (0x54) 30-byte,
  CRC-16/**big-endian**, **~7 BE16 samples + 1 status byte** frames and sends short
  `'D'` (0x44) commands (`FUN_0009EEFA`). It **votes** (median-of-3,
  `FUN_0009DFFD/DFE6`), **cross-checks** (abs-difference + debounce, `FUN_0009EE09`),
  and **gates the inverter** on agreement + peer liveness (`FUN_00098507`):
  mismatch → status bit `0x200`, peer comms-loss → bit `0x20000`. That is the
  **E027 "main vs redundant CPU sample mismatch"** mechanism.
- Separately proven (docs/23): the DSP's telemetry to the ARM is on **SCI-B =
  USART3** (the DSP has only one 19200 port); **USART2 is a *relay*, not a direct
  DSP SCI** — the leading relay candidate is this safety CPU.

So the open question is purely ARM-side: **does the safety CPU report to the ARM on
USART2** (making USART2 ⇔ safety-CPU, and the whole chain
`DSP —SCI-C— safetyCPU —USART2— ARM` provable), or does the **DSP relay** the
safety CPU's version/status to the ARM over USART3?

## Lead 1 — where does `Slave Ver` (reg 9 low byte) come from?

`HR_SLAVE_COM_VER = 9` packs **low byte = redundant-CPU firmware version**, high =
com-MCU version (`include/inv/modbus_map.h`, docs/01). The com MCU can only report
the redundant CPU's version if it **receives** it. Trace it:

- The input/holding-register getter is **`sub_0803289c`** (docs/22). Find the RAM
  it reads reg 9's **low byte** from, then find **who writes that byte**.
- **Decider:** if that byte is extracted from the **USART2 frame** (RX staging
  `0x20008084`, parsed by `sub_080259d8`/`sub_080241a8`/`sub_08024d74`), then
  **USART2 ⇔ safety CPU** — and its frame byte offset is the `Slave Ver` field. If
  instead it is lifted from the **USART3 / DSP `0x49` telemetry** (parser
  `0x0801BA98`, docs/10), the DSP is **relaying** the safety CPU's version.

## Lead 2 — where is E027 (`FAULT_CPU_SAMPLE_MISMATCH = 27`) raised?

Find where the ARM sets **fault bit 27** (it surfaces in the fault word the Modbus
slave serves; `include/inv/faults.h`). Two shapes, and which one tells you a lot:

- **Reported** — the ARM copies a *mismatch/agreement status bit* straight out of
  an incoming frame (it trusts a CPU that already decided). Then **which link that
  frame is on is the safety CPU's link.** If it's the USART2 frame, that's another
  USART2 ⇔ safety-CPU confirmation; cross-check the bit against the DSP's
  `DAT_00012318` `0x200`/`0x20000` semantics above.
- **Computed** — the ARM itself diffs two telemetry sources and raises 27. Then the
  ARM is a third cross-checker; note *which two sources* it compares (e.g. USART2
  grid samples vs USART3/DSP grid samples) — that directly reveals both CPUs'
  report links.

(Related: `WARN_FW_VERSION_MISMATCH = W008` — the ARM likely compares the three
CPU version strings; its inputs are another witness to where each version arrives.)

## Lead 3 — does the USART2 frame look like the safety CPU's own samples?

docs/22 already decoded USART2 as mode@`+4` + PV/grid-V/frequency (BE, type-1, EG4
CRC). Two quick checks sharpen "safety CPU vs relayed DSP copy":

- Is there a **version byte** and/or a **CPU-agreement/mismatch status** field in
  that frame (beyond mode + V/F)? A `Slave Ver` + mismatch flag here = safety CPU.
- Do the grid V/F values on USART2 look like an **independent measurement**
  (a second sampler) rather than byte-identical to the USART3/DSP telemetry? The
  safety CPU samples the grid itself; a pure relay would echo the DSP's numbers.

## Outcomes

- **reg 9 low byte and/or the E027 status come from the USART2 frame** ⇒
  **USART2 ⇔ safety CPU**. Combined with the DSP's SCI-C cross-check, the safety
  CPU is pinned on both ends: `DSP (SCI-C, 9600) ⇄ safety CPU ⇄ ARM (USART2, 19200
  RS-485)`. Update docs/29/22/16 to state it as proven.
- **They come from the DSP's USART3 `0x49` telemetry** ⇒ the **DSP relays** the
  safety CPU's version/status; the safety CPU is DSP-attached (SCI-C) only, and
  USART2 is a different relay/peer. Note that so the model stops assuming a direct
  ARM↔safety-CPU link.

## Reference

| what | where |
|---|---|
| redundant-CPU version | `HR_SLAVE_COM_VER = 9` (low byte), getter `sub_0803289c` |
| sample-mismatch fault | `FAULT_CPU_SAMPLE_MISMATCH = 27` (E027); version warn `W008` |
| USART2 peer | `0x40004400`, RS-485 DE on PC2; RX staging `0x20008084` |
| USART2 parsers | `sub_080259d8` (validate), `sub_080241a8` (bulk), `sub_08024d74` (mode@+4) |
| telemetry bank | `0x20009e54` (served as input regs) |
| USART3 / DSP telemetry parser | `0x0801BA98` (SOF `0x49`), docs/10 |
| DSP safety-CPU link (match target) | SCI-C `'T'`0x54/`'D'`0x44, 30-byte BE CRC-16, ~7 BE16+status; `FUN_0009EEFA`/`FUN_0009EE09`/`FUN_00098507`; status `DAT_00012318` `0x200`/`0x20000` — [`docs/29`](29-safety-cpu.md) |
