# ARM → DSP configuration protocol (USART3 ↔ SCI-B)

> **Authoritative wiring:** the ARM↔DSP link, framing and direction are distilled in [`docs/wiring/ARM-USART3-DSP/README.md`](wiring/ARM-USART3-DSP/README.md). This doc remains the deep dive on the config-push protocol.

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
**9 config blocks** (ids 0–8), re-sending the current value of every setting, not
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

## The 9 config blocks

`FUN_00092EE2` (word `0x92EE2`) switches on the block id at `[0x14]` and unpacks a
fixed sequence of fields via the endian reader `FUN_0009E7C2`. One block per
frame; ~85 fields total across the nine (ids 0–8). Each block also sets a
distinct "received" bit in `DAT_0000b300`.

> **Byte-exact field map:** the complete per-block layout — every field's frame
> offset, width, big-endian byte order, and DSP RAM target — is in
> [`docs/10-dsp-config-field-map.md`](10-dsp-config-field-map.md), for the ARM
> packer. (Notably: output priority is the single byte at frame offset **`0x1E`**
> in block 0.)

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

- **Downlink (ARM → DSP):** type-`1` frames, streaming all 9 config blocks in
  rotation, each a full snapshot. The DSP applies them as it receives them and
  marks the set complete when all blocks have arrived. A link-health flag
  (`DAT_0000AD67` bit 2) follows whether valid frames keep coming.
- **Uplink (DSP → ARM):** `FUN_0009DD14` builds a ~60-word telemetry frame at
  `0x00ADC2`, appends CRC-16, and transmits — the DSP reporting state back up.
- The DSP never issues a read request to the ARM; there is no pull path.

## Confidence & open items

- **High confidence:** the custom (non-register) block-structured layout; block
  id at `[0x14]`; the 9 blocks and their `b300` completeness bits; CRC-16
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

## ARM-side send path — located and proven (emulation)

Tracing the USART3 runtime link (`tools/emu.py`) pinned the transmit chain and,
importantly, the *shape* of the frame — but not yet the per-register offsets.

**Confirmed (emulated):**
- The USART3-runtime **send-frame** helper is `sub_0801c370(data_ptr, len)`: it
  copies `len` bytes into the link TX buffer at `0x20007490 + 0x321`, sets the TX
  length at `[0x20007490 + 0x454]`, and kicks the drain (`sub_0801c672`).
- Its **sole caller is `sub_08015094`** (a scheduler task): it calls
  `sub_0801c370(0x20009414, len)` where `len = [0x2000a922]`, **gated on
  change-detection** (it compares a few monitored values against saved copies and
  only transmits when one differs — the ARM does send on change here, while the
  DSP additionally diffs; cf. the "full snapshot" framing above).
- **The frame is a contiguous RAM snapshot.** Capturing the `sub_0801c370` call
  under emulation (RAM pre-seeded with per-word markers) returned the frame bytes
  as the exact marker sequence for `0x20009414, 0x20009416, …` — i.e.
  `sub_0801c370` copies straight from the **config image at `0x20009414`**. The
  frame layout therefore *is* the memory layout of that image; there is no
  separate field-packing step.

**Not yet extracted (honest):** the offset of each Modbus holding register inside
the `0x20009414` image (equivalently, the `0x20009048`-based config/telemetry
structure it sits in, referenced by ~18 functions). The image is maintained
incrementally by the setting-write handlers, so there is no single packer to read
the field order from; and cold emulation doesn't exercise those writers (gated),
while whole-RAM marker seeding corrupts the stored frame pointer.

**Concrete next step to finish the register→block map:** seed only the ARM
holding-register store (not all RAM, to keep pointers valid), drive the
dongle/HMI write handler for one register at a time with a distinctive value, and
read back `0x20009414` to see which offset it lands at — then correlate that
offset to the DSP block boundaries (`DAT_0000B300` completeness bits / the
`FUN_00092EE2` targets). That isolates reg→offset→block per field, with proof on
both ends. Locating the holding-register store is the prerequisite.

## UPDATE — the `0x20009414` frame builder is located (and it is request-driven)

The "packer not isolated" caveat above is now resolved. Tracing the writers of
the frame-#1 length (`0x2000a922`) and send-gate (`0x2000a920`) pins the builder:

- **`sub_08014fec` builds the `0x20009414` frame and sets its length.** It is a
  **dispatcher**: given a pointer to the USART3 **RX** buffer `0x20007490`, it reads
  a class byte `[0x20007490+1]` and calls one of `sub_0803373c` (classes 3/4),
  `sub_08033bb4`, or `fn_NOTB` (classes 0x1b–0x1d) to serialize the response into
  `0x20009414`, then stores the built length at `0x2000a922` and bumps the
  change-gate `0x2000a920` so `sub_08015094` transmits it. So the "config push"
  on this frame is actually a **response to a received request** — the peer polls,
  the ARM answers — not an unsolicited positional snapshot. (The periodic
  **clock** frame `0x20009754` *is* unsolicited; see above.)

- **`sub_0803373c` is the serializer** (byte-by-byte, `strb [frame, fp++]`).
  Emulated with settings seeded so `settings[i]==i`, a class-3 request produces a
  header: `[addr][class][SN 10 bytes = settings[1..10] at frame 0x02..0x0b][0 0 0]
  …`. The **10-byte SN is copied from `settings+0x01`** into frame offset `0x02`
  (this is the "18-byte SN+timestamp header").

- **The block payload is a Modbus-style register *range* read, not a settings
  struct copy.** Past the header the serializer walks a `[start, start+count)`
  register range (the start/count come from the request via `sub_08014dc6`) and
  for each register looks the value up in a **register-value image at
  `0x2000691c`**, 2-D-indexed by register number (e.g. one branch handles a
  16-register group as a 4×4 grid of 54-byte records). Register *values*, not raw
  settings bytes, are what gets serialized — so the DSP-visible "blocks" are
  register ranges, and `FUN_00092EE2`'s positional layout (docs/10) is the DSP's
  interpretation of a specific requested range.

**What this means for the regs-64-89 → block-3-6 map (honest status).** The
mapping is now a tractable-but-unfinished three-part chain, and it is *not* yet
proven end-to-end:
1. **reg → value image.** The grid-charge window registers (64-89) resolve to
   entries in the `0x2000691c` register image; the exact index formula per group
   still needs tracing (each request branch indexes differently).
2. **value image → frame offset.** Determined by which range the DSP requests;
   extractable by emulating `sub_0803373c` per request (the `tools/` probes do
   this — a class-3 request already yields the header layout).
3. **frame offset → DSP slot.** Already given by [`docs/10`](10-dsp-config-field-map.md)
   (blocks 3-6 triplets → `0xAD8F…`/`0xAD9C…`/`0xADAC…`).

Two blockers remain before the 64-89 map can be stated with proof: the **register
definitions for 64-89** (the EG4 18kPV-12LV holding-register table — not committed
to this repo), and the **per-group index formula** into `0x2000691c`. Until both
are in hand, the slot assignments would be guesses — deliberately not recorded
here.

### Resolved — regs 64-89 are read by *register group*, with proof

With the EG4 spec in hand both blockers clear. The spec's §2.9 states the master
may read **at most 40 registers at a time, in fixed groups (0-39, 40-79, 80-119,
…)** — which is exactly the register-range serializer found above. So the "config
blocks" the DSP ingests are **holding-register group reads**, not a bespoke
positional struct.

**The register definitions (EG4 18kPV-12LV holding table), now named in
[`modbus_map.h`](../include/inv/modbus_map.h):** regs 64-89 are three parallel
battery-schedule features, each = `PowerCMD`, `SOCLimit`, and three start/end
time windows (each window register packed `hour | minute<<8`, the same encoding
as the AC-First windows):

| regs | feature |
|---|---|
| 64-67 | charge / discharge / AC-charge power %, AC-charge SOC |
| **68-73** | **AC-charge windows 0/1/2** (start/end hour\|minute) |
| 74-75 | charge-priority power %, SOC |
| **76-81** | **charge-priority windows 0/1/2** |
| 82-83 | forced-discharge power %, SOC |
| **84-89** | **forced-discharge windows 0/1/2** |

**Frame layout, proven by emulating a group-40-79 read** (`sub_08014fec` with
`func=3`, start=40, count=40; the per-register value is fetched via `fn_ceaa`,
the register getter):

```
off 0x00  addr
off 0x01  func (0x03)
off 0x02..0x0b  SN[0..9]  (= settings+0x01)
off 0x0c..0x0d  start register (LE)   = 40
off 0x0e..0x0f  byte count (LE)       = 80  (= count*2)
off 0x10..      register values, 2 bytes each, LE, in register order
```

So **register N lands at frame offset `0x10 + (N - start)*2`.** For the group-40-79
read that puts the grid-charge schedule at:

| reg | field | frame offset |
|---|---|---|
| 64 | `HR_CHG_POWER_PCT` | `0x40` |
| 66 | `HR_ACCHG_POWER_PCT` | `0x44` |
| 67 | `HR_ACCHG_SOC_LIMIT` | `0x46` |
| **68** | **`HR_ACCHG_START_0`** | **`0x48`** |
| 69 | `HR_ACCHG_END_0` | `0x4a` |
| 70/71 | AC-charge win 1 start/end | `0x4c`/`0x4e` |
| 72/73 | AC-charge win 2 start/end | `0x50`/`0x52` |
| 76-81 | charge-priority windows | `0x58`..`0x62` |

Regs 82-89 (forced-discharge) fall in the **next** group (80-119) read, at
`0x10 + (N-80)*2`.

**Honest reconciliation note with [`docs/10`](10-dsp-config-field-map.md).** The
ARM-side frame proven here is a **Modbus read response** (`func=3`, `start`/
`bytecount` header, values at `0x10`, positional by register number). That does
**not** structurally match docs/10's DSP-side description (`type=1`, 18-byte
header, **block id @ 0x14**, payload @ `0x15`, non-register "slot triplets"):
the headers differ in length and there is no block-id byte in the read response.
So one of two things is true and needs a DSP-side cross-check before the
`regs 64-89 → block-3-6 slot offset` equivalence is asserted:
1. docs/10 analysed a **different frame/path** — most likely the **func-`0x10`
   multi-write** direction (ARM → DSP), whose header carries an extra
   count+bytecount and whose "block id" is the write's start-address field; or
2. the DSP reads these registers via the group read proven here, and docs/10's
   "blocks 3-6" are a re-expression of specific register sub-ranges.

What *is* proven end-to-end: **regs 64-89's meanings, their packed hour|minute
encoding, and that they reach the DSP as positional values in the group read at
`0x10 + (reg-start)*2`.** Mapping those onto docs/10's `0xAD8F…`/`0xAD9C…`
DSP targets is the one remaining cross-check, and it is a DSP-side question.

### The func-`0x10` write path checked — still standard Modbus, not docs/10's blocks

To test whether docs/10's `type=1`/block-id-`@0x14` frame is the **write**
direction, the func-6/`0x10` handler was traced:

- `sub_08014fec` dispatches `[RX+1]` → `sub_0803373c` for **3/4** (read),
  `sub_08033bb4` for **6/`0x10`** (write), `fn_NOTB` for `0x21/0x22/0x23`
  (the bootloader commands).
- `sub_08033bb4` builds a plain **Modbus write echo**: `[addr][func][SN[0..9] =
  settings+0x01][start-addr echo]` — no block id, no positional slot triplets.

And the link really is the DSP: the `0x20007490` buffer's drain (`sub_0801c672`)
and RX (`sub_0801c6e0`) both target **USART3 `0x40004800`**.

**So neither the read nor the write path the ARM serves on the DSP link matches
docs/10's positional-block frame.** The ARM side of USART3 is a **standard
EG4-Modbus slave** (func 3/4/6/`0x10`, SN-stamped, register groups of 40), byte-
for-byte consistent with the EG4 spec — *not* a bespoke `type=1` block protocol.
Config flows ARM→DSP by the **DSP polling the ARM** (Modbus master reads), with
the ARM owning the settings (docs/09); regs 64-89 cross as register values at
`0x10 + (reg-start)*2`.

**Reconciliation status (honest, and not unilaterally overturning docs/10).**
docs/05 noted "two protocol layers on one wire." Two possibilities remain, and
the resolution is DSP-side:
1. docs/10's `FUN_00092EE2` parses a **different frame** than the Modbus traffic
   analysed here — e.g. a separate push layer, or a different DSP SCI port — in
   which case the ARM-side builder for a docs/10-shaped frame is still unlocated
   (no ARM function was found that emits `type=1`/block-id-`@0x14`).
2. `FUN_00092EE2` is in fact parsing a **Modbus read response**, and docs/10's
   "18-byte header / block id `@0x14` / payload `@0x15`" is a mis-framing of
   `SN[10] + start + bytecount + values` (the 5-byte header delta `0x10`→`0x15`
   is the thing to re-check on the DSP side).

Until that DSP-side check is done, the `regs 64-89 → 0xAD8F…` *slot* equivalence
stays unproven; what is solid is the **Modbus register-group** path above.

## Worked example — AC-First registers 152–157 (PROVEN, ARM `.hex`)

Tracing Modbus regs 152–157 (the "AC First" load-priority time windows) through
the ARM, confirmed byte-exact against `reference/ceaa-07xx_vE_260214.bin`:

**1. Register → settings-struct offset.** The Modbus register dispatch `fn_ceaa`
(`0x08032000`) has an explicit per-register `switch`; the case stubs read the
holding-register store `0x20009854` at fixed offsets:

| Modbus reg | field | case stub | settings offset |
|---|---|---|---|
| **152** | AC First **Start** (win 0) | `0x080326a4` `ldrh [0x20009854+0x64]` | **`+0x64`** |
| **153** | AC First **End** (win 0) | `0x080326ac` `ldrh [+0x66]` | **`+0x66`** |
| 154 / 155 | Start / End (win 1) | `0x080326b4` / `0x080326bc` | `+0x68` / `+0x6a` |
| 156 / 157 | Start / End (win 2) | `0x080326c4` / `0x080326cc` | `+0x6c` / `+0x6e` |

So the three AC-First windows are a **4-byte-strided array** in the settings
struct: window *i* is `{start @ 0x64+4i, end @ 0x66+4i}`.

**2. Field encoding.** Each is a `u16 = (minute << 8) | hour`. Proof: the window
evaluator `sub_0801eb4c` reads `settings[0x64 + 4i]` both as a byte (`= hour`)
and as a halfword `>>8` (`= minute`), then computes `hour*60 + minute`
(minutes-of-day) and compares start vs end with a 1439-minute (`0x59F+…`)
day-wrap. (Notably: **the ARM itself evaluates the AC-First windows** against its
RTC here, setting an active-window status bit at `0x2000aa5e` — it is not purely
the DSP.)

**3. Change-detection → re-push.** `sub_080230b6` diffs `settings[0x64/0x66/0x68]`
against a saved mirror (`0x2000a330 + 0x4c/0x4e/0x50`) and, on a difference, sets
a pending flag (`0x2000a7a8 |= 0x100`) and updates the mirror — the hook that
makes a changed AC-First window get re-pushed to the DSP.

**4. Final hop — the windows are NOT pushed to the DSP; the ARM evaluates them
locally.** This was the open question ("which DSP block holds `settings+0x64`?").
The answer, proven by exhaustive reader-enumeration, is **none** — the AC-First
*windows* never enter the config frame. What crosses to the DSP is the *derived*
decision, not the raw times.

- **The DSP frame has exactly one builder.** A scan for every function that
  materialises the frame buffer constant `0x20009414` returns a single hit,
  `sub_08015094` (the USART3 config/telemetry state machine, buffer
  `0x20007490`). No other function builds that frame.
- **The frame builder never reads the window region.** Enumerating *every*
  reader of `settings 0x64…0x6e` (both `[base+disp]` loads and direct
  `0x20009854+off` address materialisation) gives a closed set:
  `fn_ceaa` (Modbus dispatch), the per-field accessors `sub_08008d64…e40`, the
  validator `sub_080132a0` and bulk handler `sub_080341b2`, the RTC evaluator
  `sub_0801eb4c`, and the change-detectors/mirror writers
  `sub_080230b6`/`23128`/`23818`/`23844`. `sub_08015094` is **not** in that set,
  and none of the readers builds the DSP frame.
- **Why: the DSP has no RTC** (see [`docs/09`](09-dsp-persistence-and-clock.md)),
  so it *cannot* evaluate a time-of-day window; the ARM, which owns the clock,
  must. It does, in `sub_0801eb4c`: read window `i` + the RTC struct
  (`0x2000a718`, `+1`=minute `+2`=hour), compare minutes-of-day, and write a
  per-window "inside now" bit to `0x2000aa5e`. The aggregate (any window active)
  then sets **bit 24** of the system status word `0x2000a758`, and its caller
  `sub_0801ece8` mirrors that into **bit 4 (`0x10`)** of `0x2000a8e6`.
- This is corroborated by [`docs/10`](10-dsp-config-field-map.md): the full
  byte-exact list of fields the DSP unpacks across all nine blocks contains **no
  time-of-day window pair**. The block 3–6 "slot triplets" are grid-charge
  schedule *values* (SOC/voltage), a different feature from the AC-First
  load-priority windows here.

**So the complete, proven answer to "where are regs 152/153 stored in the struct
pushed to the DSP?" is: they are not.** They live in the ARM settings struct at
`0x20009854+0x64…0x6e`; the ARM evaluates them against its own RTC and the result
feeds the output-priority / mode decision. The one link still not byte-traced is
whether the derived AC-First-active bit (`0x2000a758` bit 24) *overrides* the
pushed output-priority byte (block 0 frame offset `0x1E` → DSP `0xADA8`) or only
drives the ARM's own mode/HMI; that is the reg-145 output-priority path, a
separate subsystem from the window storage traced here.

### Emulation experiment — set the window, sweep the RTC, diff the push

`tools/emu_acfirst.py` makes the above reproducible on the real image under
Unicorn. Window 0 is seeded to **02:00–04:00** (`settings+0x64 = 0x0002`,
`+0x66 = 0x0004`) and the emulated RTC (`0x2000a718`) is moved across the edges.

**Stage A — the ARM's window evaluation is exact** (`start ≤ now < end`):

| RTC | `0x2000aa5e` | `0x2000a758` bit24 | `0x2000a8e6` bit4 | |
|---|---|---|---|---|
| 01:59 | `0x00` | 0 | 0 | off |
| **02:00** | `0x01` | 1 | 1 | **active** (start inclusive) |
| 03:59 | `0x01` | 1 | 1 | active |
| **04:00** | `0x00` | 0 | 0 | **off** (end exclusive) |

**Stage B — what the window actually changes in the push.** Running the real
DSP comms-task builder `sub_0801c11c` at an in-window time (03:00) vs an
out-of-window time (05:00) and diffing *all 64 KB of RAM*, the **only**
window-dependent bytes are the RTC input, the three derived-status locations
above, and a stack scratch holding the computed minutes-of-day (`0xB4`=180 vs
`0x12C`=300). **No byte of any DSP TX frame (`0x20009414`/`0x20009053`/
`0x20009754`) or of the comms struct changes, and no `sub_0801c370` send is
emitted.** So the window's effect stops at the ARM's own status words — a fifth,
dynamic confirmation that the AC-First *times* are not pushed as frame data.

> Honest caveat: `sub_0801c11c` is a gated scheduler task; a cold single-pass
> run does not exercise every frame-writing branch. This proves the window does
> not flow to the frame *as data* along the paths a cold run reaches; the output-
> priority modulation question is settled statically in the next section.

### Resolved — the pushed output priority is NOT window-gated

Tracing the output-priority source and the full fate of the window-active signal
settles the last open item. Output priority is **static config**, and the
window-active status is **telemetry, not a DSP input**.

**Output-priority storage is `settings+0x17`, static.** The validator
`sub_080132a0` clamps `settings[0x17] < 3` → a `{0,1,2}` field (0 Bat / 1 PV /
2 AC First — reg 145). Its **only** writers are the factory-defaults init
`sub_08012ccc` (sets `=1`), the setter, and that validator. No writer reads the
RTC or the AC-First window status, so the configured priority never changes with
the clock.

**The window-active signal's entire downstream fate** (exhaustive data-flow,
not cold emulation):

| location | produced by | consumed by |
|---|---|---|
| `0x2000aa5e` per-window mask | `sub_0801eb4c` | read back **only** inside `sub_0801eb4c` (aggregation) |
| `0x2000a758` bit24 "any window active" | `sub_0801eb4c` tail | **only** `sub_0801ece8` (the one and only bit24 consumer) |
| `0x2000a8e6` bit4 (mirror) | `sub_0801ece8` | packed into an **app/dongle telemetry** frame by `sub_080258ca` (`'A'`,type=1,`'6'` tag, in the dongle-protocol `0x08025xxx` cluster) and sent via `sub_08024dfc` |

So the signal goes window → `aa5e` → `a758` bit24 → `a8e6` bit4 → **telemetry
status**, and stops. It is never read by the DSP config builder, `a758` is never
copied wholesale into a frame, and the pushed output-priority byte is the static
`settings+0x17`. **Answer: the output priority sent to the DSP is not gated by
the AC-First time window.** The ARM evaluates the window and *reports* "AC-First
active now" to the app; it does not use it to rewrite what it pushes to the DSP.

### Resolved — the AC-charge enable word source, and how the DSP keeps time

Chasing the AC-charge enable word (block 0 offset `0x1B` → DSP `0xAD84`, bit 3 =
"AC/grid-charge enable", docs/07) answers both the gating question and the
"how is the DSP time-aware" puzzle.

**The AC-charge enable bit is static config, not window-gated.** It is one of the
`g_outputPrio==2 && (g_acChargeFlags & 8)` pair the DSP tests — "AC First selected
**and** grid charging enabled" — both read as configuration (docs/07). The
AC-First window evaluation cannot drive it: that evaluation's *entire* output
(`aa5e` → `a758` bit24 → `a8e6` bit4) is enumerated above and ends in telemetry,
and no RTC-reading function builds a config block. So bit 3 is a plain enable flag.

**How the DSP does time-of-day logic without an RTC: the ARM pushes it the clock.**
The transmit task `sub_08015094` sends *three* frames (change-gated); the third,
from **`0x20009754`**, is built by **`sub_08021df8`**: a `0xA5 0xA5` preamble
followed by the six RTC bytes of `0x2000a718` packed **year, month, day, hour,
minute, second** (`RTC+5..+0`; `+1`=minute / `+2`=hour are confirmed by the
window evaluator). So the ARM — the sole clock owner (docs/09) — **streams its
current date-time to the DSP every cycle.**

That closes the loop and separates the two "window" features cleanly:

- **Grid-charge / AC-charge schedule** (Modbus regs **64-89**, the AC-charge /
  charge-priority / forced-discharge time-window blocks): pushed to the DSP as
  the block 3-6 slot parameters, and evaluated **DSP-side** against the pushed
  clock. The AC-charge *enable* bit (`0xAD84` bit 3) just arms this.
- **AC-First output-priority windows** (Modbus regs **152-157**, this chapter's
  subject): evaluated **ARM-side** (`sub_0801eb4c` vs the RTC) and surfaced only
  as telemetry status. They are a *separate* feature from the grid-charge
  schedule and do not themselves cross to the DSP.

Net: nothing derived from the AC-First *time windows* modulates the DSP push; the
time-sensitivity the DSP does have comes from the pushed clock plus the regs-64-89
grid-charge slots, not from regs 152-157.

## ARM holding-register store FOUND — `0x20009854`

The ARM keeps its settings in a **byte-packed struct at RAM `0x20009854`** (not a
flat reg-indexed array — registers map to *named field offsets*). Evidence:

- **`sub_080132a0` is a field-by-field validator/clamp** over `0x20009854`:
  `field[0x0F]` clamped `<6`→1, `field[0x18]∈{0,3,4}`, `field[0x17]<3`→0,
  `field[0x72]<0x190`, plus bitfield sanitisation of `field[0x11]`/`field[0x13]`.
  Clamp ranges = the settings' valid ranges.
- The **HMI menu handlers write it**: `fn_Hybrid_Setting`, `fn_Smart_Load`,
  `fn_AC_Couple` all store into `0x20009854` (so an HMI edit lands here), and it
  is read across ~200 functions — the central settings store.
- The **dongle standard-Modbus** path (functions `3/4/6/0x10` only) is
  `sub_0802afe2`, a scheduler task on **UART5** (`0x40005000`); it reads/writes
  `0x20009854` by field.

### ⚠️ Retraction: `settings + 0x0B` is NOT output priority

An earlier version of this section claimed `settings + 0x0B` was output priority,
from a single `ldrh [0x20009854+0x0B]; cmp #2` read as the "is AC First?" test.
**That was a misinterpretation and is withdrawn.** Looking at the full dispatch in
`sub_0802afe2`, `[0x20009854+0x0B]` is compared against a dozen different values
(`0,2,4,5,6,8,9,0xa,0xb,0xd,0x13,0x15,0x17`), i.e. it is a **multi-valued
state/command field**, not a 0/1/2 output-priority setting; that `cmp #2` was a
state comparison. So **no register→offset field mapping is proven yet** — the
`0x20009854` struct is confirmed as the big central context/settings struct
(validated by `sub_080132a0`, written by the HMI handlers), but the per-register
field offsets inside it are still unmapped.

Lesson for this map: single `cmp` reads are not enough to pin a field — a mapping
needs the value to round-trip (write reg N via Modbus → observe the stored
offset, or read it back), which is what the driver below is for.

### Completing the map — the working method

Now that the store (`0x20009854`) and the dongle link (UART5) are known, the
efficient route is to **emulate Modbus reads on UART5** with the store pre-seeded
with per-offset markers: inject a `0x03`/`0x04` read for register N, run the
UART5 Modbus handler, and read the response — the returned value *is* the
field offset, giving `reg N → settings offset` directly, one sweep for all
registers. Then `settings offset → frame position → block` closes it (the frame
is the `0x20009414` RAM snapshot; the DSP block boundaries are the `DAT_0000B300`
completeness bits). **Status: the central struct (`0x20009854`) and the dongle
link (UART5, buffer `0x20008ca4`, TX data at `+0xc9`) are located; NO per-register
field offset is proven yet (the earlier output-priority claim was retracted).
Driving the gated dongle task to emit a register image under emulation is still
unsolved — cold runs don't build a response without a validly-injected request.**

## Reference (word addresses / DSP)

| symbol | addr | role |
|---|---|---|
| `FUN_00098F72` | `0x98F72` | app comms task: RX into `0xAC80`, CRC check, dispatch type `1` |
| `FUN_0009E309` | `0x9E309` | type-1 pre-parse; calls the deserialiser with offset `0x14` |
| `FUN_00092EE2` | `0x92EE2` | settings deserialiser (9 blocks, ids 0–8; sole caller is `FUN_0009E309`) |
| `FUN_0009E7C2` | `0x9E7C2` | frame field reader (endianness) |
| `FUN_00081034` | `0x81034` | CRC-16/Modbus (shared with the bootloader path) |
| `FUN_0009DD14` | `0x9DD14` | telemetry TX builder (`0xADC2` + CRC) |
| `FUN_0009EE62` | `0x9EE62` | clears the `0xAC80` RX buffer (`0x86` words) |
| `DAT_0000AC80` | `0xAC80` | 134-word RX control buffer (frame + trailer length/flags) |
| `DAT_0000B300` | `0xB300` | per-block "received" completeness bitmask |
| `DAT_0000AD56` | `0xAD56` | per-setting "dirty"/pending-change bits |
| `DAT_0000ADA8` | `0xADA8` | output priority (block 0; `2` = AC First) |

## The ARM evaluates the charge/discharge windows against its RTC too

Follow-up to the AC-First trace: do the **AC-charge / charge-priority /
forced-discharge** windows (regs 64-89) get evaluated against the ARM RTC, and
where do the results go? Concrete answer: **yes** — there is a second
RTC-window evaluator with byte-for-byte the same shape as the AC-First one.

**`sub_0801e1dc` — a charge/discharge window evaluator** (proven, same idiom as
`sub_0801eb4c`):
- `now = RTC.hour*60 + RTC.minute` from `0x2000a718` (`+2`=hour, `+1`=min).
- loops 3 windows reading `settings[0x3a + 4i]` as the **start** (byte = hour,
  halfword `>>8` = minute) and `settings[0x3c + 4i]` as the **end** — a
  4-byte-strided `{start, end}` array, identical to the AC-First layout at 0x64.
- `start ≤ now < end` with the same 1439-minute (`0x59f`) day-wrap.
- gated by `settings[0x33]` bits[1:3]; per-window result → status byte
  `0x2000aa55` and record arrays `0x2000a48c` / `0x2000a6dc`.

Crucially, **`settings+0x3a` is also read by `fn_ceaa`** (the Modbus register
getter), so this window register is *both* served to the DSP in the group read
*and* evaluated locally by the ARM — evaluation happens on **both** sides.

**Where the result flows — `sub_0801e608` (the schedule controller).** It calls
`sub_0801e1dc`, then combines the window verdict with:
- a 2-bit **mode** selector `settings[0x33]` bits[4:6] (0-3),
- a measured **SOC** (`0x20009e54+0xa`, in 0.1 % — the live telemetry bank), and
- an **SOC limit** (`settings+0x82`),

to set charge/discharge **control flags** `0x2000aa5c`/`0x2000aa5d`
(+ `0x2000aa57..0x2000aa5b`), and — like the AC-First path — it also folds a bit
into the telemetry status halfword `0x2000a8e6` (which `sub_080258ca` reports to
the app/dongle). So the window evaluation drives the ARM's **own** schedule
state + app telemetry; the raw window values additionally cross to the DSP via
the Modbus group read (above).

**Honest scope.** One ARM charge/discharge window evaluator is proven
(`sub_0801e1dc`, `settings+0x3a`) alongside AC-First (`sub_0801eb4c`,
`settings+0x64`); a whole-image scan for the `0x59f` day-wrap idiom finds only
these two. Whether the three named features (AC-charge / charge-priority /
forced-discharge) are each a separate window bank or are multiplexed through
`sub_0801e608`'s `settings[0x33]` mode field is **not** pinned here — the exact
register↔settings-offset identity of the `0x3a` bank was not nailed down, so it
is described as "a charge/discharge schedule window set", not labelled to one of
the three. The proven claim is narrow and solid: **the ARM evaluates these
schedule windows against its RTC, and the verdict flows to an ARM-side schedule
controller (`sub_0801e608`) + app telemetry, not into the DSP config frame.**

## CORRECTION — the earlier "DSP link is standard Modbus" reading was the *dongle* path

[`docs/10`](10-dsp-config-field-map.md) ("Is this a standard Modbus read
response? — no") pushed back on the reading above, from the DSP side: the DSP's
config frame is **big-endian, SN-less**, with a **9-way block discriminator at
`0x14`** (never a bytecount), and the DSP's own uplink uses the same symmetric
block-tagged framing — i.e. a custom **type-1 block** protocol, not the LE /
SN-stamped EG4-Modbus the ARM trace followed. **That cross-check is correct, and
I found the concrete ARM-side mechanism that proves it.**

**The serializer `sub_0803373c` is dual-mode, switched by `0x2000aa0b` bit 0:**

| `0x2000aa0b & 1` | SN? | 16-bit byte order | this is the… |
|---|---|---|---|
| **0** | `SN[10]` copied from `settings+0x01` | **little-endian** (`strb val`, then `strb val>>8`) | **dongle** path |
| **1** | **skipped** (no SN) | **big-endian** (`strb val>>8`, then `strb val`) | **DSP** path |

Both the SN-copy loop (gated `[sp]==0` at `0x080337e0`) and the value byte order
(the two branches at `0x08033ab8`/`0x08033ade`) key off the same flag; the
request-field reader likewise switches LE `sub_08014dc6` ↔ BE `sub_08014db8`.
Emulating the **BE path** (`0x2000aa0b=1`) confirms it: **no SN** (the
`settings[1..10]` markers do not appear at `frame+0x02`), big-endian values.

**So my earlier emulation forced `0x2000aa0b=0` — the LE+SN path — and therefore
characterised the *dongle* framing, not the DSP.** Concretely, the claim that
"regs 64-89 reach the DSP as LE register values at `frame 0x10 + (reg-start)*2`"
describes the **dongle** read response. The **DSP** receives the **big-endian,
SN-less, block-tagged** frame docs/10 documents (block id at `0x14`, payload at
`0x15`). The ARM is the **bridge** (docs/05's model): one shared serializer,
flag-selected, LE+SN to the external dongle and BE+block-tagged to the DSP.

**What stands, and what is retracted.** Retracted: "the ARM↔DSP link is standard
Modbus" and the LE `0x10 + (reg-start)*2` *DSP* offsets (those are the dongle's).
Still solid and DSP-independent: the **register definitions for 64-89**
(`modbus_map.h`), the **hour|minute encoding**, and the **ARM-side RTC window
evaluators** (`sub_0801eb4c` / `sub_0801e1dc`) with their results flowing to
ARM scheduling + telemetry. The exact BE DSP frame offsets for regs 64-89 should
be taken from docs/10 (the DSP side), not from the LE emulation here.

> **Hand-off:** a ready-to-run BE-mode (DSP-path) probe and the cross-check plan
> for the DSP agent are in [`docs/17`](17-dsp-frame-probe-handoff.md)
> (`tools/emu_dsp_frame_probe.py`).
