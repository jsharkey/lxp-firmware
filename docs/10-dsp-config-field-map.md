# FUN_00092EE2 field map — the ARM→DSP config block layout

Byte-exact layout of the config-push payload that the DSP's `FUN_00092EE2`
(word `0x92EE2`) unpacks into DSP RAM, for the ARM-side packer. This is the
field-level companion to [`docs/08`](08-arm-dsp-config-protocol.md) (frame
envelope + "ARM pushes a full image") and [`docs/07`](07-dsp-ac-first-mode.md)
(what block 0 drives).

Derived from the Ghidra decompile **and** a disassembly emulator of
`FUN_00092EE2` that tracks the running read offset (`*-SP[0x5]`); the two agree.
Offsets were spot-checked against the raw listing.

## Reader primitives (endianness!)

Every multi-byte field is **big-endian (MSB first)** on the wire. The buffer at
`0x00AC80` holds one wire byte per 16-bit word (low 8 bits significant), and:

| reader | returns | wire width |
|---|---|---|
| `FUN_0009E7C2(p)` | `(p[0]<<8) | p[1]` → **u16 BE** | 2 bytes |
| `FUN_0009E6BA(p)` | **u32 BE** (`p[0]`..`p[3]`, MSB first) | 4 bytes |
| direct word read (`buf[p]`) | **u8** (one wire byte) | 1 byte |

(The bootloader path uses *little*-endian readers `FUN_000810E6/D7`; the config
path does **not** — don't mix them.)

## Where the payload sits

Per [`docs/08`](08-arm-dsp-config-protocol.md): frame = `addr`(off 0) · `type=1`(off 1) ·
18-byte header(2..0x13) · **block id @ 0x14** · payload · CRC-16. `FUN_0009E309`
calls `FUN_00092EE2(0x14)`, so the **block id is the byte at offset `0x14`** and
the payload begins at **`0x15`**. One block per frame; the id selects exactly one
of the parses below. **Nine blocks, ids 0–8.** Each block ORs its own bit into
the `DAT_0000b300` "received" mask (completeness tracking — see `docs/08`).

All offsets below are **absolute frame byte offsets** (= buffer word index from
`0x00AC80`). "rsv" = a field the DSP reads and discards but which still occupies
wire bytes (the ARM must emit them; value appears unused). Targets are DSP RAM
word addresses.

---

### Block 0 (id 0) — output priority / AC-First + grid-charge core · sets `b300|=0x001`

| off | w | rd | → target | meaning |
|----|---|-----|----------|---------|
| 0x15 | 2 | BE16 | `0xAD81` | |
| 0x17 | 1 | u8 | *(cond)* | if priority<2 & ≠0 → high byte of `0xAD80` |
| 0x18 | 1 | u8 | `0xAD80` (low) | |
| 0x19 | 2 | BE16 | `0xAD83` | change-detected |
| 0x1B | 2 | BE16 | `0xAD84` | change-detected (the AC-charge enable word; bit 3 gates AC-First, see docs/07) |
| 0x1D | 1 | u8 | →`FUN_0009E2A6` | |
| 0x1E | 1 | u8 | `0xADA8` | **output priority (0 Bat / 1 PV / 2 AC First)** |
| 0x1F | 2 | BE16 | →`FUN_0009C070` arg2 | grid-charge slot |
| 0x21 | 2 | BE16 | rsv | |
| 0x23 | 2 | BE16 | →`FUN_0009C070` arg1 | grid-charge slot |
| 0x25 | 2 | BE16 | `0xAD54` | slot-enable mask |
| 0x27 | 1 | u8 | `0xAD96` | |
| 0x28 | 1 | u8 | `0xAD8D` | |
| 0x29 | 2 | — | rsv | (skipped) |
| 0x2B | 2 | BE16 | `0xAD85` | change-detected |
| 0x2D | 1 | u8 | `0xAD86` | |
| 0x2E | 1 | u8 | `0xADA9` | |

Payload ends at 0x2F (next byte is CRC or padding per the frame length).

### Block 1 (id 1) · sets `b300|=0x002`

Note: `0xB235` is read as a byte at **0x15 before** the block's internal pointer
reset to 0x16 — so it reuses the same slot block 0 reads at 0x15.

| off | w | rd | → target |
|----|---|-----|----------|
| 0x15 | 1 | u8 | `0xB235` |
| 0x16 | 2 | BE16 | `0xB236` |
| 0x18 | 2 | BE16 | `0xB237` |
| 0x1A | 2 | BE16 | `0xB238` |
| 0x1C | 2 | BE16 | `0xB239` |
| 0x1E | 2 | BE16 | `0xB23A` |
| 0x20 | 2 | BE16 | `0xB234` |
| 0x22 | 6 | — | rsv (`+8` gap) |
| 0x28 | 2 | BE16 | `0xB23B` |

### Block 2 (id 2) · sets `b300|=0x004`

All BE16. Note the `+4` after the first field (2-byte reserved gap at 0x17).

| off | → target | | off | → target |
|----|----------|--|----|----------|
| 0x15 | `0xABDB` | | 0x23 | `0xABE2` |
| 0x17 | rsv | | 0x25 | `0xABF3` |
| 0x19 | `0xABDF` | | 0x27 | `0xABF5` |
| 0x1B | `0xABE0` | | 0x29 | `0xABE3` |
| 0x1D | `0xABF7` | | 0x2B | `0xABFB` |
| 0x1F | `0xABF9` | | 0x2D | `0xABFC` |
| 0x21 | `0xABE1` | | | |

### Blocks 3–6 — grid-charge "slot" parameters (change-detect handlers)

These share a shape: a 2-byte **slot-enable mask → `0xAD54`** at 0x15, then a run
of **6-byte triplets** `[val_a(BE16), rsv(BE16), val_b(BE16)]`, each passed as
`handler(val_b, val_a)` to one of the grid-charge slot change-detect/commit
functions from [`docs/07`](07-dsp-ac-first-mode.md) (they store into the
`0xAD8F…`/`0xAD9C…`/`0xADAC…` slot records and, in AC-First, enqueue changes via
`FUN_0009C756`). A few direct scalars are interleaved.

**Block 3** (`b300|=0x008`, and `|=0x200` if the trailing value validates):

| off | w | → |
|----|---|---|
| 0x15 | 2 | `0xAD54` (mask) |
| 0x17 / 0x19 / 0x1B | 2·3 | →`FUN_0009C0C4` (0x19 = rsv) |
| 0x1D / 0x1F / 0x21 | 2·3 | →`FUN_0009C118` (0x1F = rsv) |
| 0x23 / 0x25 / 0x26 | 2+1+1 | →`FUN_0009CC77` (0x25 = rsv byte; 0x26 = u8 arg) |
| 0x27 | 1 | flag: if ==1, clears `0xB254/0xB255/0xAE2D` |
| 0x28 | 2 | `0xADA3` |
| 0x2A | 2 | `0xAD87` (stored only if `FUN_0009DA5A` validates; sets `b300|=0x200`) |

**Block 4** (`b300|=0x010`):

| off | w | → |
|----|---|---|
| 0x15 | 2 | `0xAD54` (mask) |
| 0x17 / 0x19 / 0x1B | 2·3 | →`FUN_0009CCBD` (0x19 rsv) |
| 0x1D / 0x1F / 0x21 | 2·3 | →`FUN_0009CD03` (0x1F rsv) |
| 0x23 | 2 | `0xAD8C` |
| 0x25 | 2 | `0xAD55` |
| 0x27 / 0x29 / 0x2B | 2·3 | →`FUN_0009C309` (0x29 rsv) |

**Block 5** (`b300|=0x020`):

| off | w | → |
|----|---|---|
| 0x15 | 2 | `0xAD54` (mask) |
| 0x17 / 0x19 / 0x1B | 2·3 | →`FUN_0009CD49` (0x19 rsv) |
| 0x1D / 0x1F / 0x21 | 2·3 | →`FUN_0009C7EE` (0x1F rsv) |
| 0x23 / 0x25 / 0x27 | 2·3 | →`FUN_0009C01C` (0x25 rsv) |
| 0x29 | 2 | →`FUN_0009BC08(2, …)` (AC-First command; only if `b300&1`) |

**Block 6** (`b300|=0x040`):

| off | w | → |
|----|---|---|
| 0x15 | 2 | `0xAD54` (mask) |
| 0x17 / 0x19 / 0x1B | 2·3 | →`FUN_0009CBEB` (0x19 rsv) |
| 0x1D / 0x1F / 0x21 | 2·3 | →`FUN_0009BFC8` (0x1F rsv) |
| 0x23 / 0x25 / 0x27 | 2·3 | →`FUN_0009CC31` (0x25 rsv) |

### Block 7 (id 7) · sets `b300|=0x080`

All BE16, contiguous stride 2:

| off | → | | off | → |
|----|---|--|----|---|
| 0x15 | `0xABFF` | | 0x21 | `0xAC03` |
| 0x17 | `0xAC00` | | 0x23 | `0xAC04` |
| 0x19 | `0xAC01` | | 0x25 | `0xABF4` |
| 0x1B | `0xAC02` | | 0x27 | `0xABF6` |
| 0x1D | `0xABF8` | | 0x29 | `0xABFD` |
| 0x1F | `0xABFA` | | 0x2B | `0xABFE` |

### Block 8 (id 8) · sets `b300|=0x100`

All BE16:

| off | → target |
|----|----------|
| 0x15 | `0xABDC` |
| 0x17 | `0xABDD` |
| 0x19 | `0xABE4` |
| 0x1B | `0xABE5` |

---

## Packer notes for the ARM side

- **Endianness:** every `BE16`/`BE32` field is MSB-first. Single-byte fields are
  one wire byte. Match this exactly or the DSP reads garbage.
- **Reserved words** ("rsv") still occupy their bytes — emit them (0 is the safe
  choice unless a capture shows otherwise). Block 0's `0x29` and block 1's
  `0x22–0x27` gaps likewise.
- **One block per frame.** Set the block id at offset `0x14`; the DSP parses only
  that block. Send all nine (ids 0–8) to fully configure the DSP; the DSP marks
  the set complete when `DAT_0000b300` has bits `0x001..0x100` (+`0x200` from
  block 3). Re-send continuously — the DSP diffs for changes (docs/08).
- **The "triplet → handler" fields** (blocks 3–6) are grid-charge slot
  parameters; the handler sees `(val_b, val_a)` with a reserved word between.
  Their on-DSP storage/semantics live in the `docs/07` slot-commit family.
- **Output priority** (the AC-First selector) is the single byte at **frame
  offset `0x1E`** inside block 0.

## Is this a standard Modbus read response? (cross-check — no)

A fair challenge was raised from the ARM side: that `FUN_00092EE2` is really
parsing a standard **EG4-Modbus read response** and the "block id @ `0x14`" is a
mis-framing of `SN[10] + start + bytecount + values` (the "5-byte header delta
`0x10`→`0x15`"). Re-examined from the DSP side, the evidence is **against** that —
this is the custom type-1 block protocol, not SN-stamped Modbus:

1. **`buf[0x14]` is a discriminator, not a bytecount.** Across all of
   `FUN_00092EE2` it appears only in `== 0 … == 8` tests (a 9-way switch); it is
   never used as a length/count/address. A Modbus bytecount drives a copy loop —
   this never does. So `0x14` selects a layout; it is not the Modbus header's
   byte-count byte.
2. **No `SN[10]`.** The receive path (`FUN_00098F72` → `FUN_0009E309` →
   `FUN_00092EE2`) performs **no serial-number check** on `buf[2..0x0B]`, and the
   DSP's own transmit builder shows there is no SN field at all (next point).
3. **The DSP's own uplink uses the identical, SN-less framing.** `FUN_00096EE8`
   (same SCI comms loop) builds the reply frame as `[0]=0x49` · `[1]=1` (type) ·
   `[2:3]=0x0036` (length) · fixed status at `[4..0x13]` · then
   `FUN_00092110(buf, 0x14)` fills **block data from offset `0x14`** — and
   `FUN_00092110` dispatches on the **same 9 block ids (0–8)** that `FUN_00092EE2`
   parses. So both directions share one symmetric, **block-tagged** frame with a
   20-byte header and block id at `0x14`; there is no `addr/func/SN/start/count`
   Modbus shape and no SN anywhere.
4. **Byte order is big-endian.** `FUN_0009E7C2` reads `p[0]<<8 | p[1]` (MSB
   first). The EG4 **dongle** Modbus is little-endian (`docs/08`: "values … LE,
   in register order", `0x10 + (N-start)*2`). Opposite endianness ⇒ different
   protocol.

**Reconciliation.** Both observations are correct — about **different links**.
The ARM genuinely speaks standard EG4-Modbus (func `3/4/6/0x10`, `SN[10]`, LE,
values at `0x10`) — that is the **external RS-485 dongle** path the ARM trace
followed. The **ARM↔DSP** link is the separate **type-1 block exchange** (no SN,
BE, block id at `0x14`, values at `0x15`) documented here. The cleanest model is
the one `docs/05` already proposed: the **ARM bridges** between the two — dongle
Modbus on one side, this type-1 block protocol to the DSP on the other. The
"5-byte header delta" is not a mis-frame; it is just the two protocols having
different headers (Modbus 16-byte `…start+count`, type-1 20-byte `…+block id`).

> What would change this verdict: finding, on the ARM side, that the UART which
> drives the **func-`0x10`** frames is the same one wired to the DSP (not the
> dongle). The DSP-side facts above (no SN, BE, symmetric block filler) would
> still need explaining, so the bridge model remains the most consistent.

## Confidence & open items

- **High confidence:** field order, offsets, widths, endianness, and DSP targets
  for all nine blocks — cross-validated between the decompiler's `uStack_b`
  arithmetic and an independent disassembly emulator; block 0 and the readers
  were checked against the raw listing.
- **Named vs opaque:** block 0 fields are interpreted in `docs/07`. Blocks 1–8
  targets are located (exact DSP RAM address) but most are not yet *named* as
  product settings — correlating each against the ARM-side Modbus holding-register
  map is the remaining work, and the best next step for the ARM packer to label
  its struct.
- The frame **header** fields (`0x02..0x13`, incl. the three the DSP extracts at
  `0x05`/`0x0D`/`0x13` → `0xAD60`/`0xAD82`/`0xAD5F`) are not decoded here; they
  precede the block id and are the same for every block.

## ARM-side confirmation (260214 App image): the type-1 builder/parser pinned

The hand-off in `docs/17` asked the DSP side to decide whether `FUN_00092EE2`
ingests a **func-3 read response** (values @ `0x03`) or the **type-1 block frame**
(block id @ `0x14`). Settled from *both* ends now, using the attached ARM image
(`…ceaa-07xx_vE_260214…`, an App-above-bootloader build based at `0x08005000`,
imported into Ghidra as `ARM:LE:32:Cortex`). It is the **type-1 block frame**;
the ARM builds and parses it with functions that mirror `FUN_00092EE2` exactly:

| ARM function | role |
|---|---|
| `FUN_080273b4` (`0x080273b4`) | type-1 **build wrapper** (ARM→DSP): writes the header, then calls the per-block filler with block-id offset `0x14`; rotates the block id to push the whole set |
| `FUN_08026830` (`0x08026830`) | per-block **builder**: `buf[0x14] = blockId`, then **big-endian** field values from the ARM settings struct starting at `buf[0x15]` — the mirror of `FUN_00092EE2` |
| `FUN_08025ab8` (`0x08025ab8`) | per-block **parser**, called `FUN_08025ab8(0x14)`: reads `buf[0x14]` block id + values at `buf[0x15]+` into a struct (the ARM ingesting DSP telemetry) |
| `FUN_0801bb0e` (`0x0801bb0e`) | type-1 **RX state machine**: SOF `0x49` → type `1` → length; assembles the frame |
| `FUN_0801bbe0` (`0x0801bbe0`) | the *other* RX state machine: addr + func ∈ `{0x21,0x22,0x23}` (the extended/dongle family) — a **separate** link |

### The type-1 frame, from the ARM builder `FUN_080273b4`

```
off 0x00  SOF   : 0x41 ('A') ARM→DSP   (DSP→ARM uses 0x49 'I' — see below)
off 0x01  type  : 0x01
off 0x02  0x00
off 0x03  len   : 0x36 (54)
off 0x04..0x13  fixed header: a 32-bit id/serial @0x05 (BE), status/flags, etc.
off 0x14  block id   (rotated 0..9 → the full config set is pushed in turn)
off 0x15  block payload: big-endian fields, per-block layout = this document
off  …    CRC-16 trailer
```

This is byte-for-byte what §"The 9 config blocks" documents from the DSP side
(block id @ `0x14`, BE values @ `0x15`). **It is not** `addr/func/SN[10]/start/
bytecount/values`: there is no SN, the values are big-endian, and the ARM's own
builder writes a fixed `0x41/01/00/0x36` header — so the earlier "Modbus read
response / 5-byte header delta" reading was of a *different* channel.

### Why both observations were right (the SOF asymmetry)

The two directions use **different SOF bytes**, which is why the DSP RX
(`FUN_00098F72`) checks `buf[1]==1` but never a `0x49`:

- **ARM → DSP** (config push): SOF **`0x41`**, built by `FUN_080273b4`.
- **DSP → ARM** (telemetry): SOF **`0x49`**, built by the DSP's `FUN_00096EE8`
  and checked by the ARM RX `FUN_0801bb0e`.

> **Physical port (docs/23):** the DSP transmits this `0x49` telemetry on **SCI-B**
> (`FUN_0009DD14→FUN_0009D358→`SCI-B pointer `DAT_0000aefe`) — the *same* bidirectional
> port as the config push, i.e. **ARM USART3**, not a separate SCI-A. Its `[4]` byte is
> the DSP's operating/working-state (`DAT_0000AD64`), followed by BE PV/grid/freq from
> `FUN_00092110`. So a second DSP-domain telemetry stream the ARM sees on **USART2**
> (docs/22) is **relayed**, not a direct DSP SCI-A — see [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md).

### Consequence for the regs 64-89 → DSP map

The config does **not** reach the DSP through the func-3 read path the `docs/17`
probe characterized (`reg N → 0x03+(N-start)*2`); that is a separate register-read
service. The real path is:

```
holding register  →  ARM settings struct (DAT_080274f0 / DAT_080274f4 …)
                  →  type-1 block frame (FUN_080273b4 / FUN_08026830, BE @0x15)
                  →  DSP FUN_00092EE2  →  DSP RAM (0xAD??/0xAB??/0xB2??)
```

So closing `reg N → DSP RAM target` needs the **struct-field → register-number**
leg: trace which Modbus-register write handler populates each `DAT_080274f0/f4`
field, then compose with this document's per-block offsets. That is the remaining
work; the transport and both endpoints are now proven.
