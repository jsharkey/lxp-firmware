# Factory ARM static-RAM breakdown — an investigation plan

[`docs/45`](45-arm-ram-budget.md) measured the headline: the factory ARM image
uses **~55 KB of static `.data+.bss`** (`0x20000000`–`0x2000dbd8`, ≈ 49 KB of it
zeroed `.bss`), while ours uses **~4.3 KB**. That 50 KB gap is unexplained, and
it is a **risk**: some of it is almost certainly buffers sized larger than ours
(I/O rings, register images, history/log arrays, framebuffers). If we under-size
the matching buffer, we get silent truncation / dropped data, not a build error.

This doc is a **plan, not a finding** — a set of experiments to turn the 55 KB
black box into a labelled map (`base → size → purpose → our equivalent → verdict`),
so we can spot every place our buffer should be bigger. Nothing here is run yet.

All work is **clean-room**: analyse the factory image in `lxp-factory`, carry
only *facts* (addresses, sizes, purposes) into this repo. Image is
`ceaa-07xx_vE_260214.bin` (never `com_flat.bin`; see `reference/README.md`).

## What "used" even means — three evidence sources

A byte of the 55 KB can be *allocated* (reserved by the linker) without being
*written* at runtime, and *written* without being *full*. No single method is
enough, so we triangulate, and label every number by how it was obtained:

1. **Static layout** — where each object lives and how big it is, from the image:
   base pointers + max offset, constant `memset`/`memcpy` lengths, loop bounds,
   ring wrap constants. Gives **allocated size** (strongest for exact sizes).
2. **Dynamic (emulator)** — what the running firmware actually touches and how
   often, via `tools/arm_sim.py` memory hooks. Gives **used extent + behaviour**
   (hot vs cold, where a ring wraps, which feature owns a region).
3. **Semantic** — strings and recovered symbols (`reference/strings_xref.csv`,
   `symbols.csv`, `callgraph.txt`) that name the owning function → a **purpose**.

We have no factory **symbol table**, so purposes are *inferred* — label them
`[~]` until two independent sources agree.

## Workstreams and tasks

Tasks are grouped so the three workstreams (static `RB-S*`, dynamic `RB-D*`,
semantic `RB-C*`) can run **in parallel**; the targeted hypotheses `RB-H*` draw
on all three, and the synthesis `RB-G1` is last. Status: ⬜ open · 🚧 claimed ·
✅ done. Claim one by name in a commit before you start (docs/39 convention).

### Static — segment and size the 55 KB from the image

- ⬜ **RB-S1 — base-pointer + max-offset map.** Harvest every `ldr rX,=0x2000xxxx`
  literal and `movw/movt` pair that targets `0x20000000`–`0x2000dbd8`; for each
  distinct base, find the **largest byte offset** accessed through it (extend
  `tools/ramxref.py` / `tools/disres.py`). Output: sorted `(base, inferred_size,
  #refs, owning funcs)` — the backbone segmentation. *Inferred size is an upper
  bound on the object (sparse access under-reads it); pair with RB-S2.*
- ⬜ **RB-S2 — constant `memset`/`memcpy` lengths.** Find every call to the zero
  / copy primitives with a RAM-base destination and a **constant length**
  (including the startup `.bss` clear, which bounds total `.bss`). A constant
  length *is* a buffer size. Output: `(dest_base, length, caller)`. *Strongest
  exact-size signal; do this alongside RB-S1.*
- ⬜ **RB-S3 — I/O ring sizes (wrap constants).** For each link driver/ISR —
  UART5 dongle, USART3 DSP, USART2, CAN1, the DSP link — find the RX/TX buffer
  base and the **modulo / compare constant** that wraps its index. Output: per-
  link ring capacity. (Cross-reference the `docs/wiring/` link files; record
  findings there too.)
- ⬜ **RB-S4 — array loop-bounds.** Find loops of the form `cmp idx,#N; … [base+
  idx*k]` → element count `N` and stride `k`. Targets: the Modbus register
  image length, history/log depth, parallel-unit count, per-channel energy
  arrays. Output: array dimensions.
- ⬜ **RB-S5 — anchor the known structures.** Fold in what prior docs already
  pinned — config record images `0x2000c85c` ([`docs/23`](23-arm-config-writer.md)),
  DSP telemetry struct `0x2000ce5c` ([`docs/18`](18-power-path-relays.md)),
  the live settings struct `~0x2000d850`, the Modbus register image — label
  them and subtract from the unexplained remainder.

### Dynamic — watch the running simulator

- ⬜ **RB-D1 — RAM access heatmap.** Add a Unicorn `UC_HOOK_MEM_READ|WRITE` hook
  to `arm_sim.py` that tallies, per word, read/write counts and the set of
  writer PCs. Boot + exercise → classify the 55 KB into **hot** (telemetry /
  registers, written every loop), **warm** (periodic), **cold / write-once**
  (init tables, config) and **untouched** (reserved headroom). Output: a
  segmented map with an owning PC per region.
- ⬜ **RB-D2 — differential stimulus attribution.** Snapshot RAM, apply **one**
  subsystem stimulus, diff: inject BMS CAN frames → BMS buffers; drive dongle
  Modbus reads/writes → register images + UART rings; advance the RTC / run many
  loops → energy accumulators + schedule state; trigger a fault → fault log.
  The changed bytes attribute a region to a feature. Output: `region → feature`.
- ⬜ **RB-D3 — ring high-water under flood.** Feed a long stream per link (a big
  dongle Modbus session; a CAN frame flood; many log events) and watch each
  ring's write pointer advance before it **wraps** → dynamic capacity and how
  full it gets. Confirms (or corrects) RB-S3.
- ⬜ **RB-D4 — write-once vs runtime-growing.** Diff RAM right after boot vs after
  a long run → separate init-populated const tables from buffers that grow at
  runtime (logs, accumulators, history). Reuses the RB-D1 hook.

### Semantic — put names to the regions

- ⬜ **RB-C1 — string/symbol attribution.** For each segmented region's owning
  function, pull its string xrefs and recovered name → assign a purpose
  (`fault log`, `energy_day[]`, `HMI framebuffer`, …). Promote `[~]`→`[x]` only
  when RB-S/RB-D agree with the string/symbol evidence.
- ⬜ **RB-C2 — account against the docs.** Each documented subsystem (config
  flash, DSP link, HMI, BMS CAN, energy, parallel) should claim some of the
  55 KB. Sum what the docs explain; the residual is where to dig next.

### Targeted big-buffer hypotheses (each is a quick, falsifiable probe)

- ⬜ **RB-H1 — LCD/HMI framebuffer.** Find the buffer the LCD bit-bang *reads*;
  240×160×1bpp = 4800 B, double-buffered = 9600 B? Compare to our `lcd_tft`.
- ⬜ **RB-H2 — Modbus register images.** Input (0..~152) + holding (0..~254),
  ×2 B; is it shadowed (change-detect) or per-port? Compare to our `g_rt`.
- ⬜ **RB-H3 — energy / history accumulators.** Daily + cumulative over ~10
  channels (32-bit) + any history depth — potentially several KB.
- ⬜ **RB-H4 — offline-monitoring / log staging.** The SPI data-log ring
  (`0x040000`+, [`docs/24`](24-oss-settings-region.md)) likely has a RAM staging
  buffer; find and size it.
- ⬜ **RB-H5 — parallel-inverter state.** Per-unit arrays sized for N parallel
  machines — a plausible multi-KB consumer.
- ⬜ **RB-H6 — DSP frame assembly.** RX/TX frame buffers for the ARM↔DSP link
  ([`docs/08`](08-arm-dsp-config-protocol.md)/[`docs/10`](10-dsp-config-field-map.md)/[`docs/17`](17-dsp-frame-probe-handoff.md)).

### Synthesis

- ⬜ **RB-G1 — the gap table + verdicts.** Merge everything into one table and
  land it here (or a `docs/` subdir if it grows): for each factory buffer,
  `base · size · purpose · evidence · our equivalent · our size · verdict`
  (✅ adequate · ⚠️ undersized · ❌ missing). Every ⚠️/❌ becomes a concrete
  follow-up: a buffer-size fix (cite it as a parity item in
  [`docs/39`](39-parity-roadmap.md)) or, if the factory's size looks wrong, a
  note in [`docs/31`](31-factory-quirks.md).

## Suggested order / parallelism

1. **First, in parallel:** RB-S1 + RB-S2 (static map) and RB-D1 (heatmap). These
   two independent segmentations should roughly agree — where they don't is the
   most interesting ground.
2. **Then:** RB-S3/RB-D3 (rings), RB-S4/RB-S5, RB-D2/RB-D4, RB-C1/RB-C2 — any
   order, mostly independent.
3. **Targeted** RB-H1…H6 as the map reveals big regions.
4. **Last:** RB-G1 synthesis + the buffer-sizing verdicts — the actual payoff
   for our firmware.

## Caveats

- **Allocated ≠ used ≠ full.** Always say which you measured. A ring the factory
  sized 4 KB but only fills 200 B still *needs* 4 KB if a burst can fill it — so
  the size that matters for ours is the **allocated** one (RB-S), with RB-D as
  the sanity check on whether it's ever stressed.
- **No factory symbols** — purposes are inferred; cite the tool + address +
  image, and hold findings to the `docs/45`/clean-room bar.
- **Tooling is mostly in hand:** `tools/ramxref.py`, `tools/disres.py`,
  `tools/recurse.py`, `tools/arm_sim.py`, and `reference/*.csv`. Most tasks are a
  small extension (a hook, a scan), not a new tool — keep them read-only.
