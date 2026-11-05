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

## Reference (pre-resolution)

| what | where |
|---|---|
| redundant-CPU version | `HR_SLAVE_COM_VER = 9` (low byte), getter `sub_0803289c` |
| sample-mismatch fault | `FAULT_CPU_SAMPLE_MISMATCH = 27` (E027); version warn `W008` |
| USART2 peer | `0x40004400`, RS-485 DE on PC2; RX staging `0x20008084` |
| USART2 parsers | `sub_080259d8` (validate), `sub_080241a8` (bulk), `sub_08024d74` (mode@+4) |
| telemetry bank | `0x20009e54` (served as input regs) |
| USART3 / DSP telemetry parser | `0x0801BA98` (SOF `0x49`), docs/10 |
| DSP safety-CPU link (match target) | SCI-C `'T'`0x54/`'D'`0x44, 30-byte BE CRC-16, ~7 BE16+status; `FUN_0009EEFA`/`FUN_0009EE09`/`FUN_00098507`; status `DAT_00012318` `0x200`/`0x20000` — [`docs/29`](29-safety-cpu.md) |

---

## RESOLUTION (ARM side): **PROVEN — USART2 ⇔ safety CPU.** The ARM *reports* the mismatch/version status straight out of the USART2 frame.

Resolved from the factory ARM image (`reference/com_flat.bin`), tracing the Modbus
fault/warning words back through the state classifier into the USART2 parsers. This
is the hand-off's **first outcome branch** and the **"Reported"** shape of Lead 2:
the ARM does **not** compute the cross-check — it copies a status word the USART2
peer already decided. That makes **USART2 the safety CPU's link**.

### Lead 2 (E027) — decisive: the fault word is lifted verbatim from the USART2 frame

The Modbus **fault code** is served by the input-register getter `sub_0803289c`:
reg 60 (`IR_FAULTCODE_L`) ← `STATUS(0x2000a0d8)+0x8c` (u32). The state classifier
**`sub_0801b480`** builds that word (regs: `r5=STATUS 0x2000a0d8`,
`r6=BANK 0x20009e54` = the USART2 telemetry bank, `r1=0x2000a6c4`):

```
0x0801b4a6  ldr.w  r0, [r6, #0xd4]     ; BANK+0xd4  (USART2 frame, see below)
0x0801b4aa  lsrs   r0, r0, #0xa        ; keep bits 10..31
0x0801b4ac  lsls   r0, r0, #0xa
0x0801b4ae  ldr    r1, [r1, #4]        ; 0x2000a6c4+4 (ARM-local, bits 0..9)
0x0801b4b0  lsls   r1, r1, #0x16
0x0801b4b2  lsrs   r1, r1, #0x16       ; keep bits 0..9
0x0801b4b4  orrs   r0, r1
0x0801b4b6  str.w  r0, [r5, #0x8c]     ; STATUS+0x8c = fault word (reg 60)
```

So **`STATUS+0x8c` = (`BANK+0xd4` bits 10..31) | (local bits 0..9)**. `FAULT_CPU_SAMPLE_MISMATCH = 27`
→ **bit 27 ∈ bits 10..31 ⇒ it comes from `BANK+0xd4`.** And `BANK+0xd4` is written
by the USART2 mode/status parser **`sub_08024d74`**, gated on frame length ≥ `0x54`:

```
0x08024d80  ldr    r4, =0x20009e54        ; BANK
0x08024d82  ldr    r5, =0x20008084        ; USART2 RX staging
0x08024d86  ldrb   r0, [r5, #4]
0x08024d88  strb   r0, [r4]               ; BANK+0  = frame[+4]  (operating mode)
0x08024d8a  adds   r0, r5, #5
0x08024d8c  bl     sub_08014dd4           ; BE u32 read
0x08024d90  str.w  r0, [r4, #0xd0]        ; BANK+0xd0 = BE u32 @ frame[+5]  (status A)
0x08024d94  adds.w r0, r5, #9
0x08024d98  bl     sub_08014dd4
0x08024d9c  str.w  r0, [r4, #0xd4]        ; BANK+0xd4 = BE u32 @ frame[+9]  (status B / fault)
```

(`sub_08014dd4` = big-endian u32, `[p]<<24 | [p+1]<<16 | [p+2]<<8 | [p+3]` — the
EG4/DSP BE family, same as the config/telemetry frames.) **The E027 bit is a
big-endian status word at USART2 frame offset `+9`.** The ARM trusts it wholesale;
it never diffs two sources to raise 27. → the CPU that decides the mismatch is the
**USART2 peer** = the safety CPU (DSP-side `DAT_00012318` `0x200`/`0x20000`
semantics, docs/29).

### Lead 3 (W008 + liveness) — corroborating, all on USART2

- **Version-mismatch warning.** WarnCode is served `reg 62 ← BANK+0x1e`,
  `reg 63 ← BANK+0x1c` (`sub_0803289c`). Both are parsed as BE u16 **from the USART2
  frame** in the bulk parser `sub_080241a8` (tag-0 sub-record). `WARN_FW_VERSION_MISMATCH = W008`
  is therefore **reported from the USART2 peer**, not computed by the ARM.
- **Peer identity / version bytes.** `sub_080241a8` also stores small identity bytes
  `BANK+2..6, +8` from the frame; `sub_08022c40` wipes the whole telemetry bank on a
  comms reset **but deliberately preserves exactly those bytes** — i.e. they are the
  peer's persistent identity/version, received over USART2.
- **Peer-liveness (comms-loss).** The USART2 driver `sub_080259d8` CRC-validates each
  frame (`sub_08014bec`), gates the mode/status parse on `frame[1]==1`, and
  **maintains the link-health state itself**: it debounces `0x2000a6c4` and counts
  consecutive bad/missing frames in `0x20009048+6`. The classifier sources the
  **peer-comms-loss bit (0x20000) of status word A (`STATUS+0x88`) from `0x2000a6c4`**
  (local override of the frame's bit 17) — i.e. "I lost the USART2 peer," asserted
  locally because a dead peer can't report its own death. That is the ARM-side twin
  of the DSP's `0x20000` comms-loss bit.

### Note on the reg-9 pointer (Lead 1)

The hand-off's "reg 9 via `sub_0803289c`" is imprecise for this image: input reg 9 is
`IR_PPV3` (const 0 on a 2-MPPT build), and **holding** reg 9 is served from the
settings struct `SETTINGS+9` (`0x2000985d`, written only by the flash/settings loader
`sub_080341b2`) — i.e. the com-MCU's *own* stored config, not a received version.
The *functional* content of `Slave Ver` — the peer's **version and version-mismatch
status** — nonetheless arrives on **USART2** (identity bytes `BANK+2..6,+8`; W008 in
`BANK+0x1e/0x1c`), which is what the lead was after. The exact register the slave
version is re-exported in (if any) is a loose end, not a blocker.

### Verdict

**USART2 ⇔ the redundant/safety CPU, proven on both ends.** The ARM's authoritative
operating mode *and* its fault/warning words are copied out of the USART2 frame, and
peer liveness is tracked on the USART2 link. Combined with the DSP side (docs/29: the
SCI-C `'T'`/`'D'` peer runs the median-vote + abs-diff cross-check that sets exactly
these mismatch/comms-loss bits; docs/23: USART2 is **not** a DSP SCI — the DSP's only
19200 port is SCI-B = USART3), the full chain is pinned:

```
DSP (C2000) —SCI-C 9600 'T'/'D'— safety CPU —USART2 19200 RS-485— ARM (STM32)
```

The safety CPU sits between the DSP and the ARM: it cross-checks the DSP's redundant
samples on SCI-C and reports consolidated **mode + grid/PV telemetry + agreement
(E027) / version (W008) status** to the ARM on USART2. The DSP's *direct* ARM link
(SCI-B/USART3) carries the config push (down) and a parallel `0x49` telemetry (up);
the classifier's IR_STATE + fault word are built from the **USART2/safety-CPU** bank,
so the safety CPU is the ARM's primary classified-telemetry source.

> Caveat (unchanged from docs/23/29): both DSP images on hand expose a single 19200
> ARM port (SCI-B); the SCI-C↔USART2 *pairing of the same physical MCU* is role-level
> inference (two links, same peer by behaviour) and the safety CPU's part number is
> not derivable from firmware. A schematic would seal the last gap.

