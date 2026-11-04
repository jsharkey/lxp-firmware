# ARM → DSP configuration protocol (USART3 ↔ SCI-B)

How the ARM "com" MCU hands operating settings to the TI C28x control DSP over
the inter-processor serial link. Recovered by static RE of **both** sides — the
DSP decode ([`docs/07`](07-dsp-ac-first-mode.md)) is what made this readable; see
[`docs/05`](05-dsp-link.md) for the link identification and the firmware-update
(`0x21/0x22/0x23`) path, which this document does **not** repeat.

## The two questions, answered up front

**Q: Are settings sent as Modbus register commands, or some other layout?**
Neither standard Modbus register writes nor register/value pairs. The ARM wraps
the data in the **EG4 Modbus-*family* frame envelope** (`addr`, type byte, SN,
CRC-16 — the same envelope and CRC as every other EG4 link) but the **payload is
a custom, positionally-packed binary struct**, not Modbus `0x06/0x10` writes to
numbered registers. One frame carries one **block** selected by a 1-byte block
id; the fields after it are read by fixed offset and width, not by register
address. (The standard register Modbus — functions `0x03/0x04/0x06/0x10` — is the
*external RS-485 dongle* protocol, a different link; and the firmware-update
path on this same link uses the extended `0x21/0x22/0x23` codes. The runtime
config push is its own third thing: type byte **`1`**.)

**Q: Are all settings pushed, or only edited ones?**
**All of them, as a repeating full image** — the ARM streams the complete set of
**8 config blocks** (ids 0–7), re-sending the current value of every setting, not
just the ones that changed. The DSP itself does the change detection: it
diffs each freshly-received value against its stored copy and only *acts* on a
difference. Two independent mechanisms prove this (below): a completeness
bitmask that waits for **all** blocks, and per-value diffing on receipt. The ARM
sends no "delta" encoding.

## Link recap (see docs/05 for the evidence)

- Physical: DSP **SCI-B** ↔ ARM **USART3** (all but certain; pin-map still pending
  the schematic).
- Framing: EG4 Modbus-family, CRC-16/Modbus (reflected `0xA001`). The DSP's CRC
  routine `FUN_00081034` is the twin of the ARM's `sub_08000d98`.
- Direction: **ARM is master and pushes; the DSP is a reactive slave** and never
  polls the ARM for configuration. Uplink is DSP→ARM telemetry.

## The config frame (type byte = 1)

The DSP receives frames into a **134-word control buffer at RAM `0x00AC80`**
(cleared as `0x86` words by `FUN_0009EE62`). The application comms task
`FUN_00098F72` processes it:

1. the lower receive layer deposits a frame at `0x00AC80[0..]` and writes the
   frame word-count to the trailer slot `0x00AC80[0x82]` (flags at `[0x80]`/`[0x85]`);
2. `FUN_00098F72` reads that length, recomputes CRC-16 over `frame[0 .. len-2]`
   with `FUN_00081034`, and compares it to the trailing CRC word — a frame that
   fails CRC is dropped;
3. on a good frame whose **type byte `[1] == 1`** it calls
   `FUN_0009E309 → FUN_00092EE2(0x14)`, the settings deserialiser.

Frame layout (each element is one 16-bit word = one C28x "byte"; offsets in words):

| offset | field | notes |
|---|---|---|
| `0x00` | address | EG4 framing (inferred) |
| `0x01` | **type = `1`** | selects the settings-push handler |
| `0x02 … 0x13` | SN + auxiliary header | 18 words; three fields are pulled out at `[0x05]`, `[0x0D]`, `[0x13]` (→ `ad60`/`ad82`/`ad5f`); exact subfields (serial number vs pushed timestamp) not fully mapped |
| `0x14` | **block id** (`0`–`7`) | selects which settings block follows |
| `0x15 …` | **block payload** | positional packed struct for that block (see below) |
| `len-2 … len-1` | CRC-16 | the DSP TX builder (`FUN_0009DD14`) emits it MSB-first |

There is **no register-number field anywhere** — the block id plus a fixed field
order is the entire addressing scheme.

## The 8 config blocks

`FUN_00092EE2` (word `0x92EE2`) switches on the block id at `[0x14]` and unpacks a
fixed sequence of fields via the endian reader `FUN_0009E7C2`. One block per
frame; ~85 fields total across the eight. Each block also sets a distinct
"received" bit in `DAT_0000b300`:

| block | `b300` bit | target variable cluster | likely content |
|---|---|---|---|
| 0 | `0x001` | `ad80–ada9` (incl. `ada8`) | **output priority / AC-First + grid-charge config** — see [`docs/07`](07-dsp-ac-first-mode.md) |
| 1 | `0x002` | `b234–b23b` | (unmapped group) |
| 2 | `0x004` | `abdb–abfc` (~12 fields) | (unmapped group — largest block) |
| 3 | `0x008` (+`0x200`) | `ad54`, `b254/b255`, `ada3`, `ad87` | (unmapped) |
| 4 | `0x010` | `ad54`, `ad8c`, `ad55` | (unmapped) |
| 5 | `0x020` | `ad54` … | (unmapped) |
| 6 | `0x040` | `ad54` … | (unmapped) |
| 7 | `0x080` (+`0x100`) | `abff–abfe`, `abdc–abe5` | (unmapped group) |

(Field-level semantics of blocks 1–7 are not yet recovered; block 0 is fully
decoded in `docs/07`. The `0x00AD??`/`0x00AB??`/`0x00B2??` addresses are the DSP's
live settings RAM.)

## Why "all, not deltas" — the two proofs

**1. A completeness bitmask.** Every block ORs its own bit into `DAT_0000b300`
(block 0 → `0x001`, … block 7 → `0x080`, plus `0x100`/`0x200` from blocks 7/3).
`FUN_00098F72` only declares the configuration valid (`DAT_0000ad51 |= 0x200`)
once **all** of bits `0x001 … 0x200` are present — i.e. it is explicitly waiting
to have received the *entire set* of blocks. That design only makes sense if the
ARM sends the full set every cycle.

**2. Per-value change detection on the DSP.** Inside each block the DSP compares
the freshly-parsed value to its stored copy before doing anything, e.g. block 0:

```c
if ((uStack_5 != DAT_0000ad83) || (iVar1 != DAT_0000ad84) || (iVar4 != DAT_0000ad85)) {
    DAT_0000ad83 = uStack_5; DAT_0000ad84 = iVar1; DAT_0000ad85 = iVar4;   // store
    ... FUN_0009C756(...);                                                 // enqueue the *change*
}
```

If the ARM only sent edited settings, the DSP would have nothing to diff against
and no reason to carry "dirty" bits (`DAT_0000ad56`) and a change queue
(`FUN_0009C756` → ring buffer `0x00AA94`). The diffing exists precisely because
the same full values arrive repeatedly; **the DSP, not the ARM, works out what
changed**, and routes those deltas onward (e.g. the AC-First grid-charge commits
in `docs/07`).

## Direction and cadence

- **Downlink (ARM → DSP):** type-`1` frames, streaming all 8 config blocks in
  rotation, each a full snapshot. The DSP applies them as it receives them and
  marks the set complete when all blocks have arrived. A link-health flag
  (`DAT_0000AD67` bit 2) follows whether valid frames keep coming.
- **Uplink (DSP → ARM):** `FUN_0009DD14` builds a ~60-word telemetry frame at
  `0x00ADC2`, appends CRC-16, and transmits — the DSP reporting state back up.
- The DSP never issues a read request to the ARM; there is no pull path.

## Confidence & open items

- **High confidence:** the custom (non-register) block-structured layout; block
  id at `[0x14]`; the 8 blocks and their `b300` completeness bits; CRC-16
  validation; ARM-push / DSP-slave direction; full-image (not delta) pushing;
  block 0 = the AC-First group.
- **Partial:** the 18-word header (`[0x02..0x13]`) — SN is expected there and the
  ARM is the system timekeeper, so a pushed timestamp is plausible, but the exact
  subfields are not mapped. The lower SCI-B receive layer that fills `0x00AC80`
  (direct ISR vs DMA) was not traced; only the processing task was.
- **Pending the schematic:** the physical ARM-USART3 ↔ DSP-SCI-B pin pairing (the
  frame-length/CRC/vocabulary match makes it all but certain).
- **Next:** map the header timestamp fields; recover field semantics for blocks
  1–7 by correlating their target RAM with the ARM-side Modbus holding-register
  map; and trace the uplink telemetry payload (`FUN_00096EE8` fills `0x00ADC2`).

## ARM-side: trigger/cadence and this repo's implementation

**Trigger — confirmed periodic, not edit-driven (ARM RE).** The config push is a
registered task in a cooperative scheduler, not something fired on a setting
change:

- `sub_0803e4c8` sets up the scheduler and registers periodic tasks via
  `sub_0803e728(fn)`; `sub_0803e69a` is the per-dispatch task runner and calls
  the comms task `sub_080140e8` every cycle (`sub_0802e780 → sub_0803e4c8 → …`).
- So the ARM re-emits the full block set on a fixed cadence regardless of whether
  anything changed — matching the DSP-side evidence (completeness bitmask + per-
  value diffing). **The answer to "what triggers a write to the DSP" is: a timer/
  scheduler tick — it is always pushed, continuously, as a full snapshot.**

**Reimplementation** (`src/dsp/`, bound to the shared holding-register model so an
HMI edit or dongle write is simply picked up by the next snapshot):

- `include/inv/dsp_link.h` / `src/dsp/dsp_config.c` — frame builder (addr, type 1,
  18-byte SN+timestamp header, block id, payload, CRC-16) + the 8-block rotation
  (`dsp_push_next`). Per-block payloads come from an **editable field table**;
  block 0 (AC-First / output-priority group) has a best-effort field list,
  blocks 1–7 frame correctly with an empty payload until decoded.
- `src/dsp/dsp_link_port.c` — polled USART3 TX of a built frame.
- `tests/test_dsp_config.c` — host tests (`make test`, 35 checks): frame layout,
  CRC validity, 8-block rotation, and that a changed value re-appears in the next
  full snapshot.
- Wired into `main.c`: one block pushed per ~20 ms (full snapshot ~6×/s).

**Open item flagged to RE (ARM TX path).** The USART3 TX *queue* I traced on the
ARM (`sub_0800103a`, the `0x20000028+0x321` buffer) is only reached from the
firmware-update / extended (`0x21/0x22/0x23`) paths — **not** from a type-1
config builder. So either the type-1 push uses a different USART3 TX mechanism
than that buffer, or (less likely, given this doc's DSP-side evidence) the ARM
UART for the config push differs from USART3. The DSP-side framing is solid; the
exact ARM-side *emit* site is still unpinned and worth confirming (the Unicorn
harness can capture it once the faulting cold-start state is seeded).

## ARM-side link map — USART3 CONFIRMED (and the packer hunt)

Investigated with the Unicorn harness (`tools/emu.py`, now with `stubs`/`stop_at`)
and static RE. Results, separating confirmed from not-yet-proven:

**Confirmed (ARM side):**
- **The DSP link is USART3** — no longer just "all but certain". The runtime
  parser `sub_0801c3e6` is driven by `sub_0801c6e0`, which references USART3
  (`0x40004800`). The per-UART runtime clusters are clean: USART3
  `sub_0801c2ea/0801c672/0801c6e0`, USART2 `…c792/c992/c9ec`, UART5, UART4.
- **Two protocol layers share USART3** (matches docs/05's "two framings, one
  transport"): the **bootloader / firmware-update** path (`0x21/0x22/0x23`, RX
  buffer `0x20000028`, dispatch `sub_08001482 → sub_08001420`) and the
  **runtime config/telemetry** path (link buffer `0x20007490`, RX frame at
  `[0..0x31F]`, **TX frame at `+0x321`**, drained to USART3 by `sub_0801c672`).
- **The runtime DSP comms task is `sub_0801c11c`** — a scheduler-registered
  periodic task (via `sub_0803e4c8`), re-confirming the push is continuous.

**Not yet proven (honest):** the byte-level **packer** — the exact code that
writes each holding-register value into each block's payload — was **not
isolated**. Store-offset heuristics flagged status structures, not the frame;
and cold emulation doesn't exercise the packer because (a) it is gated by
runtime flags that are 0 from a cold start, so most sub-builders early-return,
and (b) the ARM settings RAM is zero, so any frame that *is* built is empty. No
writes to the `0x20007490+0x321` TX region were observed in a cold single pass.

**Recommended path to the full register→block map.** The mapping is more
tractably proven from the **DSP deserialiser `FUN_00092EE2`** (already decoded
in Ghidra, docs/07): its field read-order per block + the DSP RAM targets
(`0x00AD??`/`0x00AB??`/`0x00B2??`) + the register semantics give block→register
directly. The one field proven so far is **block 0: output priority = Modbus
reg 145 → `g_outputPrio` (0x00ADA8)** (docs/07). To confirm from the ARM side,
the next harness step is: locate the ARM holding-register store (via the dongle
Modbus write handler), seed it + the gating flags, then emulate `sub_0801c11c`
and read the frame assembled at `0x20007490+0x321`. Until then, blocks 1–7 field
semantics remain unmapped and the `src/dsp/dsp_config.c` field tables stay as
clearly-marked stubs.

## Reference (word addresses / DSP)

| symbol | addr | role |
|---|---|---|
| `FUN_00098F72` | `0x98F72` | app comms task: RX into `0xAC80`, CRC check, dispatch type `1` |
| `FUN_0009E309` | `0x9E309` | type-1 pre-parse; calls the deserialiser with offset `0x14` |
| `FUN_00092EE2` | `0x92EE2` | settings deserialiser (8 blocks; sole caller is `FUN_0009E309`) |
| `FUN_0009E7C2` | `0x9E7C2` | frame field reader (endianness) |
| `FUN_00081034` | `0x81034` | CRC-16/Modbus (shared with the bootloader path) |
| `FUN_0009DD14` | `0x9DD14` | telemetry TX builder (`0xADC2` + CRC) |
| `FUN_0009EE62` | `0x9EE62` | clears the `0xAC80` RX buffer (`0x86` words) |
| `DAT_0000AC80` | `0xAC80` | 134-word RX control buffer (frame + trailer length/flags) |
| `DAT_0000B300` | `0xB300` | per-block "received" completeness bitmask |
| `DAT_0000AD56` | `0xAD56` | per-setting "dirty"/pending-change bits |
| `DAT_0000ADA8` | `0xADA8` | output priority (block 0; `2` = AC First) |
