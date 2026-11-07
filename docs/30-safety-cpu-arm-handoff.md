# Hand-off to the ARM agent: pin the safety CPU via `Slave Ver` (reg 9) + E027

> **Authoritative wiring:** the USART2↔safety-CPU link is distilled in [`docs/wiring/ARM-USART2-safety.md`](wiring/ARM-USART2-safety.md). This doc remains the ARM-side resolution detail.

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

Resolved from the factory ARM image (`reference/ceaa-07xx_vE_260214.bin`), tracing the Modbus
fault/warning words back through the state classifier into the USART2 parsers. This
is the hand-off's **first outcome branch** and the **"Reported"** shape of Lead 2:
the ARM does **not** compute the cross-check — it copies a status word the USART2
peer already decided. That makes **USART2 the safety CPU's link**.

> **Correction (this revision):** an earlier version of this section had the **fault
> and warning words swapped** (it put the fault code at `STATUS+0x8c`/`BANK+0xd4`/frame
> `+9` and claimed W008 came from `BANK+0x1e/0x1c`). The register sweep in
> [`docs/33`](33-usart2-telemetry-bank.md) corrected it: **fault = `STATUS+0x88` ←
> `BANK+0xd0` ← frame `+5`**, **warn = `STATUS+0x8c` ← `BANK+0xd4` ← frame `+9`**, and
> `BANK+0x1e/0x1c` are **radiator temperatures** (IR 65/66), not the warn code. The
> verdict is unchanged — both status words still come from the USART2 frame — but the
> offsets below are the corrected ones.

### Lead 2 (E027) — decisive: the fault word is lifted verbatim from the USART2 frame

The Modbus **fault code** is served by the input-register getter `sub_0803289c`:
reg 60/61 (`IR_FAULTCODE_L/H`) ← `STATUS(0x2000a0d8)+0x88` (u32). The state classifier
**`sub_0801b480`** builds that word (regs: `r5=STATUS 0x2000a0d8`,
`r6=BANK 0x20009e54` = the USART2 telemetry bank, `r1=0x2000a6c4` = the ARM-local
fault/warn accumulator):

```
; --- FAULT word (reg 60/61) ---
0x0801b48e  ldr.w  r2, [r6, #0xd0]     ; BANK+0xd0  (USART2 frame +5, see below)
0x0801b492  ...     r0 = 0xfffdfffe    ; mask: clear bits 0 and 17
0x0801b496  ands   r2, r0
0x0801b498  ldr    r3, [r1]            ; 0x2000a6c4  (ARM-local accumulator)
0x0801b49a  ...     r0 = 0x00020001    ; keep bits 0 (E000) and 17 (E017)
0x0801b49e  ands   r3, r0
0x0801b4a0  orrs   r2, r3
0x0801b4a2  str.w  r2, [r5, #0x88]     ; STATUS+0x88 = FAULT word (reg 60/61)
; --- WARN word (reg 62/63) ---
0x0801b4a6  ldr.w  r0, [r6, #0xd4]     ; BANK+0xd4  (USART2 frame +9)
0x0801b4aa  lsrs/lsls #0xa             ; keep bits 10..31 from the frame
0x0801b4ae  ldr    r1, [r1, #4]        ; 0x2000a6c4+4 (ARM-local, bits 0..9)
0x0801b4b0  lsls/lsrs #0x16            ; keep bits 0..9 local
0x0801b4b4  orrs   r0, r1
0x0801b4b6  str.w  r0, [r5, #0x8c]     ; STATUS+0x8c = WARN word (reg 62/63)
```

So **`STATUS+0x88` (fault) = (`BANK+0xd0` with bits 0,17 cleared) | (local bits 0,17)`.**
`FAULT_CPU_SAMPLE_MISMATCH = 27` → bit 27 is **not** bit 0 or 17, so **it is copied
straight from `BANK+0xd0`.** Only the two *internal-comm* fault bits are asserted
locally: **E000** (bit 0) and **E017** (bit 17 = `0x20000`) — these are the ARM's own
"I lost the link" faults, which a dead peer cannot report. `BANK+0xd0` is written by
the USART2 mode/status parser **`sub_08024d74`**, gated on frame length ≥ `0x54`:

```
0x08024d80  ldr    r4, =0x20009e54        ; BANK
0x08024d82  ldr    r5, =0x20008084        ; USART2 RX staging
0x08024d86  ldrb   r0, [r5, #4]
0x08024d88  strb   r0, [r4]               ; BANK+0   = frame[+4]  (operating mode)
0x08024d8a  adds   r0, r5, #5
0x08024d8c  bl     sub_08014dd4           ; BE u32 read
0x08024d90  str.w  r0, [r4, #0xd0]        ; BANK+0xd0 = BE u32 @ frame[+5]  (FAULT status)
0x08024d94  adds.w r0, r5, #9
0x08024d98  bl     sub_08014dd4
0x08024d9c  str.w  r0, [r4, #0xd4]        ; BANK+0xd4 = BE u32 @ frame[+9]  (WARN status)
```

(`sub_08014dd4` = big-endian u32, `[p]<<24 | [p+1]<<16 | [p+2]<<8 | [p+3]` — the
EG4/DSP BE family, same as the config/telemetry frames.) **E027 is bit 27 of a
big-endian status word at USART2 frame offset `+5`.** The ARM trusts it wholesale;
it never diffs two sources to raise 27. → the CPU that decides the mismatch is the
**USART2 peer** = the safety CPU (DSP-side `DAT_00012318` `0x200`/`0x20000`
semantics, docs/29).

### Lead 3 (warnings + version + liveness) — corroborating, all on USART2

- **Grid-domain warnings arrive on USART2.** The WARN word (reg 62/63 ← `STATUS+0x8c`)
  takes bits **10..31 from `BANK+0xd4`** = the USART2 frame `+9` status dword — so the
  DSP/grid-domain warnings (e.g. `W016` grid outage = bit 16, `W017` grid-V range,
  `W018` grid-F range) are **reported from the USART2 peer**. Its low bits (0..9),
  including `W008 FW-version-mismatch`, come from the ARM-local accumulator
  `0x2000a6c4+4` instead — i.e. **W008 is ARM-*computed*** (the ARM compares the
  versions it holds; see docs/32), not copied from the frame. (This corrects the
  earlier claim that W008 was a frame field.)
- **Peer version byte.** The Control-CPU (DSP) version the ARM reports (HR 10 low) is
  `BANK+2`, a byte of the **USART2 frame** (docs/32); `sub_080241a8` writes the small
  identity/version bytes `BANK+2..6,+8`, and `sub_08022c40` wipes the telemetry bank on
  a comms reset **but deliberately preserves exactly those bytes** — the peer's
  persistent identity, received over USART2.
- **Peer-liveness (comms-loss).** The USART2 driver `sub_080259d8` CRC-validates each
  frame (`sub_08014bec`), gates the mode/status parse on `frame[1]==1`, and
  **maintains the link-health state itself**: it debounces `0x2000a6c4` and counts
  consecutive bad/missing frames in `0x20009048+6`. The classifier then asserts the
  **E017 bit (`0x20000`) of the fault word from `0x2000a6c4`** (local override of the
  frame's bit 17) — "I lost the USART2 peer," the ARM-side twin of the DSP's `0x20000`
  comms-loss bit.
  - **Ours (T08).** Implemented: once a CRC-valid frame has been seen, `src/main.c`
    raises `INV_LOCAL_FAULT_E017` when `safety_rx_link_ok(now, SAFETY_LINK_TIMEOUT_MS)`
    is false and clears it on the next good frame (hooks in `safety_rx_port.c`, T05;
    tested by `test_safety_link_loss_raises_e017`). The factory's exact threshold is
    **not observable in the bare harness** — feeding the USART2 wire then going silent
    never moves `0x2000a6c4`/`0x20009048+6` or sets E017, because that frame-health
    bookkeeping runs in the unscheduled periodic USART2 task — so our timeout is a
    conservative default pending a bench capture; the mechanism is as pinned above.

### E000 = the DSP (USART3) link (07 RE, T08)

The two ARM-local internal-comm fault bits the classifier keeps (mask `0x00020001` of
the local accumulator) are **E017** (bit 17 = USART2/safety, above) and **E000**
(bit 0). E000 is now confirmed by static RE of the 07 image (`com_flat.bin`) to be the
**DSP/USART3** link fault, not just an elimination guess:

- The 07 ARM-local fault accumulator is **`0x2000d808`** (the 07 twin of 05's
  `0x2000a6c4`); the re-pinned classifier `sub_0801a678` reads it with the same
  `0x00020001` keep-mask that `sub_0801b480` used in the 05 image.
- **E000 (bit 0) is set inside the DSP config-push frame builder `sub_080273b4`** — the
  function that assembles the 9-block config the ARM sends the DSP over USART3 (T10).
  At `0x080276f4..fc` it does `r0 = &0x2000d808; [r0] |= 1`, i.e. raises E000, gated on
  DSP-link health: `0x2000d9c8` bit 10 (`0x080276c6`) and `0x2000d890` bit 13
  (`0x080276e6`, the same health word whose bit 10 drives W008). That E000 is asserted
  on the **DSP-push path**, from DSP-link health, is what ties bit 0 to USART3.
- The **DSP-RX reset/timeout handler `sub_080359b8`** zeroes the DSP frame-buffer
  struct at `0x2000d7b0`, arms a `0x12c` (300) reload counter, and sets a health bit —
  the link-reset bookkeeping behind the health words above.

**Ours (T08).** The DSP polls the ARM as a Modbus master on USART3 (T09), so a served
poll is our liveness signal. `dsp_rx_port.c` stamps the last served poll and exposes
`dsp_rx_requests()` / `dsp_rx_link_ok(now, timeout)`; once a poll has been seen,
`src/main.c` raises **E000** (`INV_LOCAL_FAULT_E000`) when none arrives within
`DSP_LINK_TIMEOUT_MS` and clears it on the next poll. Tested e2e by
`test_dsp_link_loss_raises_e000` (`tests/test_arm_sim_self_only.py`). The exact factory
threshold is sim-blocked (the `0x12c` counter runs in an unscheduled periodic task),
so the timeout is a conservative default; the bit and behaviour are as pinned above.

### Note on the reg-9 pointer (Lead 1)

The hand-off's "reg 9 via `sub_0803289c`" is imprecise for this image: input reg 9 is
`IR_PPV3` (const 0 on a 2-MPPT build), and **holding** reg 9 is served from the
settings struct `SETTINGS+9` (`0x2000985d`, written only by the flash/settings loader
`sub_080341b2`) — i.e. the com-MCU's *own* stored config, not a received version.
The *functional* content of `Slave Ver` — the peer's version — nonetheless arrives on
**USART2**: the Control-CPU (DSP) version is `BANK+2` (HR 10 low, docs/32), and the
identity bytes `BANK+2..6,+8` are preserved across a comms reset. The exact register
the *redundant*-CPU version is re-exported in is a loose end (reg 9 low is hard-`0x00`
in this 12000XP image), not a blocker.

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

