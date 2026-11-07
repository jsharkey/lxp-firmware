# Field provenance — holding register → ARM struct → DSP block offset

> **ARM↔DSP link.** Closes (as far as the firmware allows) the leg from a dongle
> **holding register** through the **ARM settings/working RAM** to the **DSP config
> block offset** documented per-block in this tree. See the [index](fields.md).

## The real builder (in `ceaa-07xx_vE_260214.bin`)

docs/10 named the push builder `FUN_080273b4`/`FUN_08026830`. Those Ghidra addresses
are **flat `0x08000000`-based** (the whole image, bootloader + App), so they resolve
directly in `reference/ceaa-07xx_vE_260214.bin`:

| function | role |
|---|---|
| `0x080273b4` | **frame builder**: writes the header (`[0]=0x41`, `[1]=1`, `[2]=0`, `[3]=0x36` length, `[4]=0`, status from the 07 STATUS struct), then calls the per-block filler per block id |
| `0x08026830(buf, 0x14, block_id)` | **per-block filler**: `buf[0x14]=block_id`, then big-endian field values from the ARM working RAM into `buf[0x15]+` — the mirror of the DSP's `FUN_00092EE2` |

> **Correction (05→07 re-pin).** An earlier revision of this section "converted" the
> Ghidra addresses by *subtracting* a `0x5000` App base, landing on `sub_080258ca` /
> `sub_08024dfc`. Those are 05-era artifacts: at `0x08024dfc` in this 07 flat image
> the code is **mid-function** (it dereferences the `0x14` arg as a pointer and writes
> nothing), which is why the config-push oracle returned all-zeros. The correct
> builder/filler are the Ghidra addresses read as-is at the flat base (above). The
> live oracle (`tests/dsppush_contract.py`) now uses `0x08026830` and, after quiescing
> the RTOS engine for the call, reproduces every block — blocks 2/7/8 come out unity
> `0x0400` byte-for-byte, confirming the spec.

The maps below are from emulating the filler `0x08026830` for each block id 0–8 and
recording, for every payload byte it writes, **which RAM address it read** (reliable —
it is the real builder, not a guess).

> **Settings-base caveat.** The source struct is written as `0x20009854` below. That
> is also the **05-series** settings base, while the 07 time-window/config evaluators
> definitively use `0x2000c85c`. Whether the `0x20009854` the 07 builder reads is a
> distinct 07 struct or a stale-05 carry-over is **not yet verified** — see the
> ambiguity note in [`reference/README.md`](../../../reference/README.md). The struct
> **offsets** below are base-relative and hold either way.

## The key finding: the push serializes DERIVED WORKING state, not raw registers

The builder does **not** read the holding-register settings struct field-by-field.
It reads four ARM-internal regions, most of them **one processing step removed** from
the holding registers:

| region | addresses | blocks | what it is |
|---|---|---|---|
| **slot records** | `0x2000a330`–`0x2000a390` | 0, 3, 4, 5, 6 | grid-charge / AC-First **slot records**, *computed* from the schedule (writers `sub_08022e8c`/`sub_08023746`/`sub_08023b30`, the `docs/07` slot-commit family) |
| **battery limits** | `0x2000a68c`–`0x2000a69f` | 1 | battery charge/discharge **limits**, *computed* from BMS + settings (writers `sub_0800adc8`/`sub_0800db42`/`sub_0801ddc0`) |
| **ext-settings** | `0x20009908`–`0x20009944` | 2, 7, 8 | a settings area **default-initialised to `0x400`** by `sub_08012f66`; **not** served by the holding getter `fn_ceaa` (so no read-register exposes it) |
| **canonical settings** | `0x20009854`–`0x20009906` | 0, 3 (a few) | the holding-register settings struct — these fields **do** map to a holding register (via `fn_ceaa`) |
| slot-enable mask | `0x2000a7a8` | 0, 3–6 | → DSP `0xAD54` (the per-slot active mask) |
| status/misc | `0x2000a0e0`, `0x2000a169`, `0x2000a172`, `0x2000a9e8`, `0x2000a936` | 0, 8 | live status, not settings |

So a holding register reaches the DSP as:
`holding reg → (write handler / periodic compute) → working struct → block field → DSP RAM`.
The middle hop is real work (schedule → slot records, BMS → limits), **not** a copy —
which is why the config isn't a register image on the wire.

## Directly-mapped fields (holding register confirmed)

Where the builder reads the canonical settings struct, the holding register is known
(from the `fn_ceaa` map below). Confirmed:

| block·off | ARM source | holding reg | DSP target (docs/10) | note |
|---|---|---|---|---|
| **0 · `0x28`** | `0x2000986c` | **HR 20 `PVInputModel`** | `0xAD8D` | validated by offset + name |
| 3 · `0x28` | `0x20009883` | **HR 119** | — | reg from `fn_ceaa`; DSP target not aligned here |
| 3 · `0x2a` | `0x2000987e` | **HR 19** | `0xAD87` (validated) | — |

**Output priority / AC-First** (the headline field, [`block-00`](block-00-output-priority.md)):
the builder reads it from the **working** location `0x2000a343` (low byte → block 0
`0x1E` → DSP `0xADA8`), *not* directly from its holding register **HR 145
`OutputPrioConfig`**. So `HR 145 → (write) 0x2000a343 → block0[0x1E] → 0xADA8` — the
value is correct, but it travels through the working copy, consistent with the
"derived, not raw" model.

## Schedule time-windows → slot records → blocks 4/5 (the HR 64–89 leg, CLOSED)

This is the intermediate hop the status section used to list as open: how the
dongle **schedule** holding registers reach the slot records that blocks 3–6
serialize. It is closed for the **time-window** fields, by emulating the
**slot-committer family** (the 34 functions that write the dirty mask
`0x2000a7a8`). Each committer copies specific settings-struct fields into a slot
record and sets its dirty bit; the block filler (`sub_08024dfc`) later reads those
slot records into the frame. Composing the two halves (committer: settings→slot,
filler: slot→offset) gives an end-to-end, register-exact chain:

| dongle feature | holding regs | committer(s) | slot record | DSP block·offset |
|---|---|---|---|---|
| **AC-charge** windows (w0s/w0e/w1s/w1e/w2s/w2e) | **HR 68/69/70/71/72/73** | `sub_08022fde`, `sub_08023044` | `0x2000a370`–`0x2000a37a` | **block 4 `0x17`/`0x19`/`0x1B`/`0x1D`/`0x1F`/`0x21`** |
| **AC-First** windows (w0s/w0e/w1s/w1e/w2s/w2e) | **HR 152/153/154/155/156/157** | `sub_080230b6`, `sub_08023128` | `0x2000a37c`–`0x2000a386` | **block 5 `0x17`/`0x19`/`0x1B`/`0x1D`/`0x1F`/`0x21`** |

So `HR 68 → (committer sub_08022fde) → slot 0x2000a370 → (filler) → block4[0x17] → DSP`,
and the five siblings follow in order. **Gating:** a committer only copies when its
feature-enable bit in `0x2000a7a4` is set; otherwise the slot keeps its prior value.
The window packing is unchanged on the wire (`low=hour`, `high=minute`,
[dongle doc](../../wiring/ARM-UART5-dongle/HR064_089-charge-discharge-schedule.md)).

**This refines the old "triplet with reserved middle word" model** in
[`block-03_06`](block-03_06-gridcharge-slots.md): the ARM writes **six sequential
u16 window values** into `0x17…0x21`, so `0x19` and `0x1F` are **not** reserved —
they carry the window-*end* values (HR 69/72 for AC-charge, HR 153/156 for AC-First).
The real grouping is three `(start,end)` pairs `(0x17,0x19)`,`(0x1B,0x1D)`,`(0x1F,0x21)`,
not `(0x17,0x1B)` with `0x19` dropped.

### The rest of the schedule — now settled by live capture

The static marker method only tags the **canonical settings struct**
(`0x20009854…`, what `fn_ceaa` serves); the remaining schedule registers are not in
it, so the trace above could not speak to them. A **live USART3 capture** now does —
write the register over the dongle, serialize the snapshot with the real builder,
and diff the frame bytes ([`tests/test_dsp_push.py`](../../../tests/test_dsp_push.py),
the method field-provenance called for). Result on the factory image:

| register(s) | writable? | pushed to the DSP? |
|---|---|---|
| AC-charge **power** HR 66 | yes (reads back) | **NO** — stored, but no config-frame byte moves |
| AC-charge **SOC** HR 67 | **no** (write not stored) | — inert in this image |
| **Charge-priority** HR 74–81 | **no** | — whole feature inert in this image |
| **Forced-discharge** HR 82–89 | **no** | — whole feature inert in this image |
| general charge/discharge power HR 64/65 | yes | (not probed for push) |

So: **HR 66 is confirmed stored-but-not-pushed**, and **HR 67 + HR 74–89 are not
even writable here** — the AC-charge-SOC, charge-priority and forced-discharge
schedule features are inert in this firmware, so there is nothing to push. This is
the empirical complement to the static finding (they are absent from the settings
struct and from every committer read), and it supersedes the earlier "absence of
evidence" hedge for these registers in *this* image. (A different variant that
exposes those features could push them; the capture is per-image.)

## Per-block ARM-source map (reliable)

Each row: payload offset, width (bytes the source occupies), and the ARM RAM it is
read from (classified above). **HR n** = a canonical-settings field with a known
holding register.

### Block 0
| off | w | ARM source |
|---|---|---|
| `0x15` | 2 | settings `0x20009861` |
| `0x17` | 2 | settings `0x2000985f` |
| `0x19` | 2 | slot-record `0x2000a330` |
| `0x1b` | 2 | slot-record `0x2000a332` |
| `0x1d` | 2 | slot-record `0x2000a343` (low byte = **output priority** → `0xADA8`) |
| `0x1f` | 2 | slot-record `0x2000a336` |
| `0x21` | 2 | slot-record `0x2000a338` |
| `0x23`/`0x24` | 1+1 | slot-record `0x2000a33a`/`0x2000a33b` |
| `0x25` | 2 | slot mask `0x2000a7a8` → `0xAD54` |
| `0x27` | 1 | status `0x2000a169` |
| `0x28` | 1 | **HR 20 `PVInputModel`** → `0xAD8D` |
| `0x29` | 2 | status `0x2000a0e0` |
| `0x2b` | 2 | slot-record `0x2000a334` |
| `0x2d` | 1 | status `0x2000a9e8` |
| `0x2e` | 1 | status `0x2000a172` |

### Block 1 — all from the battery-limits working struct `0x2000a68c…0x2000a69f`
`0x15`←`a68c` · `0x16`←`a69f` · `0x17`←`a69e` · `0x18`←`a690` · `0x1a`←`a692` ·
`0x1c`←`a698` · `0x1e`←`a69a` · `0x20`(8B)←`a68e` · `0x28`←`a69c`.

### Block 2 — all from ext-settings `0x20009912…0x20009934`
`0x15`(4B)←`9914` · `0x19`←`991a` · `0x1b`←`991e` · `0x1d`←`991c` · `0x1f`←`9920` ·
`0x21`←`9912` · `0x23`←`9922` · `0x25`←`9924` · `0x27`←`9926` · `0x29`←`9928` ·
`0x2b`←`9932` · `0x2d`←`9934`.

### Block 3
`0x15`←slot mask · `0x17`←`a33c` · `0x19`←`a33e` · `0x1b`←`a342` · `0x1c`←`a340` ·
`0x1d`←`a344` · `0x1f`←`a346` · `0x21`←`a348` · `0x22`←`a349` · `0x23`←`a350` ·
`0x25`←`a352` · `0x26`←`a354` · **`0x28`←HR 119** · **`0x2a`←HR 19 → `0xAD87`**.

### Blocks 4, 5, 6 — all slot records + slot mask
Block 4: mask, then `a370 a372 a374 a376 a378 a37a`, mask, `a36a a36c a36e a36f`.
Block 5: mask, then `a37c a37e a380 a382 a384 a386 a362 a364 a366 a367 a368 a388`.
Block 6: mask, then `a356 a358 a35a a34a a34c a34e a34f a35c a35e a360`.

### Block 7 — all from ext-settings `0x20009936…0x20009944` + `0x2000992a…0x20009930`
`0x15`←`9936` · `0x17`←`9938` · `0x19`←`993a` · `0x1b`←`993c` · `0x1d`←`992a` ·
`0x1f`←`992c` · `0x21`←`993e` · `0x23`←`9940` · `0x25`←`992e` · `0x27`←`9930` ·
`0x29`←`9942` · `0x2b`←`9944`.

### Block 8
`0x15`←ext-settings `990a` · `0x17`←`990c` · `0x19`←status `0x2000a936` · `0x1b`←`9910`.

## Appendix — holding register → canonical settings offset (`fn_ceaa`)

The read getter `fn_ceaa` (`0x08032000`) maps **89** holding registers to the
canonical settings struct `0x20009854`. This is the reg↔struct half for the fields the
builder reads from that struct (and a useful map in its own right for the ARM packer).
Selected entries (full sweep in the commit that landed this doc):

| settings addr | HR | | settings addr | HR |
|---|---|---|---|---|
| `+0x18` `0x986c` | 20 `PVInputModel` | | `+0x3a` `0x988e` | 68 (AC-charge window) |
| `+0x13` `0x9867` | 21 `FuncEn` | | `…0x9898` | 73 |
| `+0x2a` `0x987e` | 19 | | `0x98b8…0x98c2` | 152–157 (AC-First windows) |
| `+0x2f` `0x9883` | 119 | | `0x98c4`/`0x98c6` | 147/148 (battery capacity) |
| `0x98f0…0x98f9` | 103–109 (lead-acid) | | `0x9900…0x9906` | 194–198 (generator charge) |

**Correction (supersedes an earlier note here):** the AC-First **window times**
HR 152–157 *are* pushed to the DSP — the earlier claim that they "are not read by any
config block" was wrong. The config **filler** doesn't read them from the settings
struct directly; the **slot-committer** `sub_080230b6`/`sub_08023128` copies them
`settings 0x200098b8…0x200098c2 → slot 0x2000a37c…0x2000a386`, and block 5 serializes
that slot record to `0x17…0x21` (see the schedule-windows section above). What is
*not* pushed is the per-window **active verdict** (ARM evaluates the window against
the RTC, docs/07); the window **times** themselves travel to the DSP.

## Status — what's closed, what's left

- **Closed:** the **struct → block offset** half, completely — every payload field of
  all 9 blocks is mapped to its exact ARM source address and source struct, from the
  real builder.
- **Closed (subset):** **holding reg → block** for the fields the builder reads
  directly from the canonical settings struct (HR 20 → block0; HR 19/119 → block3;
  plus the `fn_ceaa` map).
- **Closed (schedule windows):** the **holding reg → slot record → block** chain for
  the **AC-charge** window times (HR 68–73 → block 4) and the **AC-First** window
  times (HR 152–157 → block 5), via the slot-committer family — see the
  schedule-windows section above. This also corrected the stale "HR 152–157 not
  pushed" note.
- **Open (one layer):** the derived regions the committer trace can't see because
  they are **not** in the canonical settings struct — the schedule **power/SOC** (HR
  66/67) and the **charge-priority / forced-discharge** features (HR 74–89), plus the
  **battery limits** area. These need the intermediate writers
  traced or a **live USART3 capture** (write a holding reg over the dongle, watch which
  `0x41`-frame byte changes) — the definitive method, since the push is not
  scheduler-driven in the `arm_sim` harness.

## Reimplementation status (ours) — T10

Our packer ([`src/dsp/dsp_config.c`](../../../src/dsp/dsp_config.c)) now emits a
**fixed-length frame** (payload `0x15..0x33`, CRC at `0x34..0x35`, total `0x36` —
the factory's length byte) so the payload region is directly comparable byte-for-byte.
Per block, against the factory oracle ([`tests/test_dsp_push.py`](../../../tests/test_dsp_push.py)):

| block | ours | parity |
|---|---|---|
| **2, 7, 8** (calibration gains) | **done** — constant unity defaults | **byte-identical** (any state) ✓ |
| 4, 5 (schedule windows) | done (slot-committer) | window region `0x17..0x22` ✓; the rest of the slot record (power/V/SOC) still empty |
| 0 | best-effort stub (ours' own layout: priority @`0x15`) | **not** byte-identical — needs the grid-charge slot-record derivation |
| 3, 6 | empty | needs the grid-charge slot-record derivation (`0x2000a330…a360`) |
| 1 | empty (matches only at the no-BMS boot state) | **blocked on T11** (battery-limit struct `0x2000a68c…`) |

**Hand-offs** (what each remaining block needs):
- **Block 1** → the battery-limit working struct `0x2000a68c…0x2000a69f`, computed
  from BMS + settings — that derivation is **T11**.
- **Blocks 0, 3, 6** → the full grid-charge **slot-record** derivation
  (`0x2000a330…0x2000a360`): the slot-committer (`src/dsp/dsp_slots.c`) currently
  commits only the time-**window** fields (blocks 4/5); the slot power/voltage/SOC
  fields are the "open one layer" above and need their writers traced or a live
  capture.
  - **T02 re-attempt (2026-11-07, committer now runs under `enable_rtos()`).**
    With the RTOS scheduler running, the committer *does* populate `0x2000a330…`
    from dongle writes — confirmed live. Capturing the factory's blocks 3/6 under
    different writes shows they are **derived from the output priority**: writing
    **HR 145** (OutputPrioConfig = AC-First) or **HR 19** *zeroes* the grid-charge
    slot fields of blocks 3 and 6, HR 119 drives block 3 `@0x29`, HR 120/66 drive
    `@0x16`. So blocks 3/6 are **not** constant — a byte-exact fill must replicate
    the output-priority-gated slot-record derivation (still the open work; T02
    unblocked observing it, not implementing it). The **battery-limit** inputs
    some fields read are **T11**.
- **Header parity (separate task):** ours' frame header is still the earlier
  SN+timestamp layout; the factory header is `[0]=0x41`, `[1]=1`, `[3]=0x36` len,
  status `[5:8]` (the real builder `sub_080258ca`). The payload region is now exact,
  but the header bytes are not — a [`frame-header`](frame-header.md) follow-up, not
  part of the block-payload work.
