# 45 — Daybreak: feature flags, register window, and persistence for new features

**Daybreak** is the codename for *our* open-source firmware's beyond-factory
features. (The factory-parity reimplementation is just "ours". Daybreak is what
it can do on top.)

**Status: design, adopted as the plan of record; nothing here is implemented yet.**
The build tasks are in [`docs/39`](39-parity-roadmap.md):
- **T28**: the control plane and the front-panel key chords;
- **T29**: the Daybreak settings store;
- **T30**: HR 11 `AlltoDefault` parity, which the factory-reset chord reuses.

The register allocation is authoritative in
[`docs/wiring/ARM-UART5-dongle/registers.md`](wiring/ARM-UART5-dongle/registers.md)
("Address-space allocation"). The control-block registers are
[`HR10000_10039-Daybreak-feature-control.md`](wiring/ARM-UART5-dongle/HR10000_10039-Daybreak-feature-control.md)
and [`IR10000_10039-Daybreak-capability.md`](wiring/ARM-UART5-dongle/IR10000_10039-Daybreak-capability.md).
The feature *ideas* are in [`docs/38`](38-oss-feature-ideas.md). This doc says how
any of them gets built.

## The problem

Most of the effort in this repo has gone into one property: **our firmware behaves
like the factory `ceaa-07xx` image**. The oracle-first suites pin it: `make test`,
`make test-sim`, `make regsweep`, `make wrsem`, the cross-image persistence tests
and the rest ([`docs/39`](39-parity-roadmap.md)). Daybreak features change
behaviour on purpose. If they land as ordinary code, each one erodes that property
a little. After a dozen, nobody could say which behaviour is the factory's and
which is ours.

## The rule

> **Out of the box, our firmware is the factory mirror.** With every Daybreak flag
> clear, it must pass every existing parity test unchanged. That is the default, and
> also the state after a fresh flash or a reset. It must also answer every register
> outside the Daybreak control block exactly as it does today. A feature changes
> behaviour **only** while its flag is set.

Everything below is how that is enforced mechanically, so that it doesn't rest on
reviewers noticing.

---

## 1. Two layers of gating

| layer | what it is | who sets it | default |
|---|---|---|---|
| **Build: `ENABLE_DAYBREAK`** | `make` (= `ENABLE_DAYBREAK=0`) is the **pure mirror**: no Daybreak code at all, not even the control block. `make ENABLE_DAYBREAK=1` compiles Daybreak in, with every feature runtime-off. | the builder | `0` |
| **Run time: the feature-enable mask** | one bit per feature in **HR 10000–10007** (128 feature IDs). Writable over the dongle bus. Persisted only on an explicit SAVE (§4). | the user, HA, a test | **all zero** |

Why both layers:
- The **build flag** makes the rule cheap to prove. CI builds both images and runs
  the whole existing suite against each. If their verdicts differ with the mask at
  zero, a feature has leaked out of its gate (§6.1).
- The **runtime mask** is what users and tests actually touch. One
  `ENABLE_DAYBREAK=1` image covers every combination of features. There are no
  per-feature builds, and trying a feature doesn't need a reflash.

Names in code: `daybreak_feat_active(DAYBREAK_F_<NAME>)` is the gate. The
registry lives in `include/inv/daybreak_features.h`, the bodies in `src/daybreak/`.
With `ENABLE_DAYBREAK=0`, `daybreak_feat_active()` folds to constant `0`, so every
hook compiles away.

A compile-time *default mask* (`make ENABLE_DAYBREAK=1 DAYBREAK_DEFAULT_MASK=…`) is
allowed for **bench builds only**. An example is arming the bug-report recorder
(docs/38 §6.1) from first power-on during hardware bring-up. Release builds and
every CI parity job use the zero default, and the build warns when it isn't zero.

## 2. The register surface (summary; the per-register files are authoritative)

All addresses are raw 0-based protocol addresses, as everywhere in this tree, not
Modicon `3xxxx`/`4xxxx` notation.

### 2.1 Where the Daybreak window sits, and why there

The Daybreak window is **IR 10000–10999 and HR 10000–10999**: 25 blocks of 40
registers, aligned to the dongle query groups (10000 = 250 × 40). An earlier draft
(docs/38 §2) used 1000–1399. We moved it because the factory's own register space
is visibly still growing, and 1000 left too little room:

| evidence | what it shows |
|---|---|
| spec PDF | IR up to 152, HR up to 198 |
| live 12000XP capture ([`docs/34`](34-multi-battery-can.md), `tools/lxp_pcap.py --reg 127`) | the factory serves **non-zero IR 174, 193–194, 199–200, 203–204**: beyond-spec registers already in use |
| same capture | the dongle uploads **IR 0–380** and **IR 5000–5126** every cycle, so the cloud already *reads* to IR 380 |
| factory read path `sub_0801ef68` ([`docs/44`](44-dongle-modbus-crash-surface.md)) | rejects HR reads landing in **4095–4999** and table-serves the battery bank from **5000**, so the vendor's own plan runs to at least ~5000 |

So the factory's namespace is treated as **0–9999** in both spaces (the full table is
in `registers.md`). Daybreak starts at 10000, beyond every number the factory
references. A reserved Daybreak growth band sits at 11000–19999.

### 2.2 What the factory does with that window (proven, dynamic)

Measured on `ceaa-07xx_vE_260214` in the harness: USART3 register slave
(`ModbusDsp`), using the `regsweep_contract` and `settings_contract` factory
backends, 2026-11-08.

| probe | factory result |
|---|---|
| read IR/HR 10000–10007, 10039–10046, 20000, 32768 | **served, all `0`** |
| write-single HR 10000 (values 0 and 1), HR 10016 | **exception 2**, nothing stored (read-back `0`) |
| write-multiple HR 10000 ×4 | no echo, read-back `0` |
| HR 21 after all of the above | still answers (ARM alive) |

That gives us two properties for free:
- **Discovery.** A client reads IR 10000–10001. The factory returns `0,0`; Daybreak
  returns `DAYBREAK_MAGIC` (`"DAYB"`). There is no guessing, and probing a factory
  unit has no side-effects.
- **Safe on the factory.** A client that writes flags to a unit running factory
  firmware gets exception 2 and nothing changes. A stale HA configuration can't
  harm a unit that was flashed back to factory.

⚠️ This is the factory's **USART3** register slave, our harness oracle. The real
UART5 dongle task (`sub_0802afe2`) can't run in the harness yet (T02). Both share the
read/write server audited in docs/44, so the same answer is expected, but it is
**~ inferred** for UART5 until T02 or a bench capture.

### 2.3 Block 0: the control plane (always present in `ENABLE_DAYBREAK=1`)

Block 0 is the **only** part of the window that answers while the mask is zero. It
holds no feature behaviour, only discovery and the switches.

| reg | name | summary |
|---|---|---|
| **IR 10000–10001** | `DAYBREAK_MAGIC` | `0x4441 0x5942` (`"DA" "YB"`). The factory reads `0,0`. |
| IR 10002 | `DAYBREAK_SCHEMA` | register-schema version, `major<<8 \| minor` |
| IR 10003 | `DAYBREAK_CTL_STATUS` | safe-mode boot, dirty, last-write-rejected, save-failed, store-degraded |
| IR 10008–10015 | `FEAT_SUPPORTED[0..7]` | compiled into this build *and* applicable to this variant |
| IR 10016–10023 | `FEAT_ACTIVE[0..7]` | enabled **and** with dependencies and runtime preconditions holding |
| IR 10024–10031 | `FEAT_SAVED[0..7]` | the mask in the saved snapshot (what the next boot loads) |
| **HR 10000–10007** | `FEAT_EN[0..7]` | **the running feature-enable mask** |
| HR 10008–10015 | — | reserved for mask growth to 256 IDs |
| HR 10016 | `FEAT_CMD` | `0x5341` SAVE · `0x524C` RELOAD · `0x434C` CLEAR (§4.3) |

Bit numbering in every mask: **feature ID *n* is bit `n % 16` of word `n / 16`**.
Each word is a plain 16-bit register, never a 32-bit pair, so the dongle's
reversed-word rule never applies.

### 2.4 Feature blocks

A feature that needs registers claims one or more 40-register **blocks** *k* (1–24)
at **10000 + 40·k**, the same *k* in **both** spaces. Telemetry goes on the IR
side; settings and commands go on the HR side. So "feature X has block 5" means
IR 10200–10239 and HR 10200–10239. Blocks are claimed alongside the feature ID
(§3).

**While a feature is not ACTIVE, its blocks answer exactly as unmapped registers do
today: exception 2 for reads and writes.** Turning a feature off returns its corner
of the address space to today's behaviour too.

## 3. Feature registry: IDs are claimed, not pre-planned

There is **no up-front ID plan**. IDs and blocks are handed out as features are
started, through the **claims table below**. Several agents work in parallel, so
the table, not anyone's memory, is how you avoid trampling another agent.

### 3.1 How to claim (do this *before* writing feature code)

1. `git pull --rebase origin main` and read the table as it stands on `main`.
2. Add one row: the **next free ID** (one past the highest row, tombstones
   included), the **next free block(s)** if the feature has registers, and any
   **flash sectors** if it needs its own log ring (§4.5). Set its status to 🚧 and
   name the docs/39 task.
3. Commit **the claim on its own** (`docs/45: claim Daybreak feature <ID> (<name>)`)
   and push it at once, before the code.
4. **Collision rule (same as `docs/NN`):** if your rebase shows someone else landed
   the same ID, block or sector first, you are the later arrival. Take the next
   free one and fix your references in the same commit.
5. When the feature's first implementation lands, its row goes ✅ and its ID, block
   and sectors are **frozen forever**.

Registry rules:
- **IDs are permanent.** A retired feature's row becomes a 🪦 tombstone. Its bit,
  blocks and sectors are never reused, so a client holding an old mask, or a flash
  snapshot holding old settings, can never switch on something different.
- **ID 0 is reserved** and is never a feature. A mask word of `0x0001` is therefore
  always an error, which catches clients that confuse "on" with "bit 0".
- **One behaviour per bit.** Don't build a "fix all quirks" bit. Each docs/31 quirk
  fix gets its own ID, so a user can take one fix without another, and a failing
  test points at exactly one change.
- **`requires` may only name a lower ID.** Dependencies always point down the mask,
  which keeps incremental validation simple (see the HR file).
- `include/inv/daybreak_features.h` mirrors this table, and the T28 checker fails
  `make test` if they drift.

### 3.2 Claims table

| ID | feature | IR/HR block(s) | flash sectors (§4.5) | requires | conflicts | task | status |
|---|---|---|---|---|---|---|---|
| 0 | *reserved, never a feature* | — | — | — | — | — | 🔒 |

## 4. Persistence: where Daybreak settings live on flash

### 4.1 What the current layer can and can't do (as of this commit)

- **RAM.** The Modbus holding image is a dense `uint16_t holding_reg[256]`
  (`src/main.c`), and both `mb_rd_hold` and `mb_wr_hold` refuse any `a >= 256` with
  exception 2. Nothing at 10000+ fits, and a dense array sized for HR 10999 (22 KB)
  would be absurd on this MCU.
- **Flash.** Persistence goes through `SETTINGS_MAP` (`include/inv/settings_map.h`).
  That is a *sparse* table mapping each HR to a (factory slot, byte offset, width,
  scale) inside the factory's 250-byte slot payloads, which is how the factory
  round-trip stays byte-compatible. The HR *number* never becomes a storage offset,
  so a high HR doesn't create a gap. But the factory slots are the wrong home for
  Daybreak data: their spare bytes are unmapped factory territory, and a
  flash-back to factory would revert or misread anything we put there (docs/24
  "Do not co-locate inside a factory slot ring").

So Daybreak needs its own RAM routing and its own store. The existing factory
persistence path stays exactly as it is.

### 4.2 RAM routing

The Modbus port gets one hook, compiled only under `ENABLE_DAYBREAK=1`:
`10000 ≤ a < 11000` → `daybreak_mb_read/write(space, a, …)`. That dispatches by
block to the owning feature, or to the control plane for block 0. Each feature owns
its registers' storage in its own module, and the registry carries a descriptor per
register: `{reg, default, min, max, persist}`. `holding_reg[256]` is untouched and
there is no 1000-entry array. RAM cost is proportional to the registers that
exist, not to the address span.

### 4.3 The Daybreak settings store: sparse snapshots on the docs/24 region

Daybreak gets its **own** wear-levelled ring in the docs/24 region, which the
factory never reads:

```
SPI-NOR 0x010000 ┌──────────────────────────────┐
                 │ Daybreak SETTINGS ring       │ 64 KB = 16 × 4 KB sectors = 256 pages
                 │ (snapshot journal, below)    │
        0x020000 ├──────────────────────────────┤
                 │ feature-owned rings          │ 128 KB = 32 sectors, claimed per
                 │ (event journal, logs, …)     │ feature in §3.2 (§4.5)
        0x040000 └──────────────────────────────┘ factory data-log ring starts here
```

**Pages** reuse the docs/24 geometry unchanged: 256 B, CRC-16/MODBUS over
`[0x00:0xFA]`, marker `0x5A` at `[0xFF]` (factory-rejectable). The page magic
becomes **`"DAYB"`**, matching the IR magic; docs/24's draft `"LXP1"` was never
implemented. Page payload (246 B):

```
+0x00  u32  generation      monotonically increasing per SAVE
+0x04  u8   page_index      0 .. page_count-1
+0x05  u8   page_count      pages in this generation
+0x06  u16  entry_count     entries on this page
+0x08  entries[]            up to 59 × { u16 reg, u16 value }, sorted by reg
```

**Packing is by key, not by position.** A snapshot holds only the persisted
registers whose value **differs from the registry default**, as `(reg, value)`
pairs. The mask words (HR 10000–10007) are ordinary entries. So:
- **no gaps**: an empty window costs nothing, and a fully-default unit (the mirror
  state) has an *empty* snapshot;
- **no fixed layout to renumber**: adding a feature, claiming block 17 before
  block 3, or retiring a feature never moves another feature's data. The HR
  address is the key, and addresses are frozen by the claims table;
- **bounded size**: even if every one of the 1000 window registers were persisted
  and non-default, that is 17 pages (≈ 4.3 KB) per snapshot. A realistic one is 1–2
  pages.

**Commit and recovery** (power-fail safe):
- A SAVE writes generation *g+1* as `page_count` consecutive pages. A generation is
  valid only if **all** its pages are present with valid CRCs. On boot the loader
  takes the **newest complete** generation. A SAVE torn by a power cut leaves *g*
  as the winner.
- The writer erases the next sector **ahead** of the write pointer, and never erases
  a sector holding the newest complete generation.
- On load, each entry is checked against its registry descriptor (range). An
  invalid value falls back to its default and sets `CTL_STATUS.store_degraded`.
- **Unknown keys are carried, not dropped.** An entry for a register this build
  doesn't know (feature compiled out, or saved by a newer build) is kept in a
  bounded carry list and rewritten on the next SAVE. Flashing an older or smaller
  build and pressing SAVE therefore doesn't silently wipe another feature's
  settings. Only CLEAR drops carried entries.
- **Wear:** 256 pages per ring, typically 1–2 pages per SAVE, at about 100 k
  erase cycles per sector, gives on the order of 10⁷ SAVEs. Writes only happen on
  SAVE, so wear is a non-issue.

Alternatives considered and rejected:
- a **dense image** indexed by `reg − 10000`: 2 KB (8 pages) of mostly default
  values per SAVE, plus a fixed layout that every new feature must slot into;
- **squeezing into factory slots**: the factory-round-trip and co-location hazards
  in §4.1;
- **one ring per feature for settings**: fragments wear-levelling, and makes "save
  the whole Daybreak state atomically" impossible.

### 4.4 When things are written

- **The whole Daybreak state is RAM-only until `FEAT_CMD = SAVE`.** That covers the
  mask *and* every `persist` register. SAVE commits them together as one atomic
  generation, so the saved mask and the saved settings always come from the same
  moment.
- Trying a feature or a setting is therefore always undone by a power cycle. That
  is the main safety net on real hardware.
- Registers whose descriptor says `persist = no` (commands, leases, per-boot
  overrides) are never stored at all.
- Boot: the newest complete generation is loaded into RAM. With no valid
  generation, everything is default and the mask is zero, so a fresh flash boots
  as the mirror.
- If HA users find explicit SAVE awkward, a per-register `persist = auto` (debounced
  autosave) can be added later. It must never apply to the mask words.
- **Not a dumping ground for factory-surface gaps.** Some factory HRs (HR 100/144/148,
  194–198, per `settings_map.h`) aren't persisted by ours yet. They belong in the
  factory slots where the factory keeps them (parity work), never in the Daybreak
  store, because a factory round-trip would lose them.

### 4.5 Feature-owned rings (the "other wear-levelling slot")

High-churn data isn't settings: an event journal (docs/38 §3.8), high-resolution
logs (§6.3), a persisted bug-report capture. It must not share the settings ring,
or it would wear it and push settings snapshots out. A feature that needs that kind
of storage **claims whole 4 KB sectors inside `0x020000–0x03FFFF`** in its §3.2 row,
and runs its own ring there with the same page format (marker `0x5A`, magic
`"DAYB"`, and its feature ID in the page header so a stray page can't be misread).
CLEAR and the factory-reset chord erase every claimed ring as well as the settings
ring.

## 5. Code rules for a feature

These are reviewable rules. T28 adds a lint for the first two.

1. **One gate function.** Every feature entry point checks
   `daybreak_feat_active(DAYBREAK_F_<NAME>)`. That is a single inlined bit test
   against the ACTIVE mask, latched once per scheduler tick. No feature code runs
   on any other condition.
2. **Features live in `src/daybreak/`**, one file per feature, beside the control
   plane `src/daybreak/daybreak_features.c`. The parity trunk (`src/modbus`,
   `src/bms`, `src/sched`, …) gets **hooks**, never feature bodies. A hook is the
   narrowest possible seam. For example the IR getter does
   `v = factory_value(); if (daybreak_feat_active(DAYBREAK_F_Q1_FIX)) v = daybreak_q1_ir101(v);`.
   The factory computation always runs and stays testable; the feature only
   overrides its output.
3. **Parity code never reads Daybreak state.** Information flows one way only, from
   the trunk to the feature. A trunk module that starts branching on Daybreak
   settings fails review.
4. **Off means off within one tick.** When a feature's bit clears, or its
   preconditions drop, it must within one tick release every lease, return every
   peripheral it drove to trunk control, and stop changing any factory-surface value.
   Its RAM settings stay as they were, and so does its saved snapshot.
5. **Daybreak settings go in the Daybreak store only** (§4). A feature never makes
   the factory slots differ from what the trunk would write. A unit flashed back to
   factory must not be able to tell a feature ever ran.
6. **The safety envelope never moves** (docs/38 §1.3). No flag can unlock a value
   outside what the factory HMI accepts.
7. **Remote control of the power path needs authorization.** The first feature that
   commands relays or setpoints over the wire must also bring (or `require`) a
   write-authorization feature with a front-panel "remote control: allow" gate
   (docs/38 §5.4). Every later such feature `require`s it. Without it, any RS-485
   master (including the cloud behind the dongle) could grant itself actuation.
   Feature flags themselves are as writable as any factory setting. The dongle can
   already write HR 21 or reboot the unit with HR 11 (docs/31 Q14).

## 6. Testing strategy

### 6.1 The parity gate: existing tests, untouched

- **The entire existing suite runs unmodified with the mask at zero.** No existing
  test may be edited to know about Daybreak. If a parity test needs editing because
  of a feature, that feature leaked out of its gate.
- `make test-parity` (T28) builds **`ENABLE_DAYBREAK=0`** and **`ENABLE_DAYBREAK=1`**
  and runs `make test`, `make test-sim`, `make regsweep` and `make wrsem` against
  both. Their verdicts must be identical. Block 0 sits outside every existing sweep
  range (IR 0-159, HR 0-255, IR 5000-5126).
- Sim tests boot from an **erased Daybreak region**, so the saved mask is zero.
  ⚠️ **Key pins in the harness:** only a few contracts (`regsweep_contract.py`,
  `can_tx_contract.py`) drive the key pins high (released). Elsewhere the emulated
  IDR defaults to `0`, so all four active-low keys read *pressed* at boot. The
  chord detector must therefore treat "all four pressed" as **no chord** (§7). T28
  also makes "keys released" the harness default, and a parity test boots with all
  four keys low to prove that no chord fires.
- A fixture that reuses a flash image across tests must erase the Daybreak region,
  or send `FEAT_CMD = CLEAR`, between tests, so a feature test can never leak flags
  into a parity test.

### 6.2 Feature tests: flags as a precondition

Every feature test **turns on exactly the flags it needs as its first step** and
asserts they took effect:

```python
# tests/daybreak_helpers.py  (T28)
def daybreak_enable(mb, *feature_ids):
    """Precondition: set exactly these features (and nothing else) in the
    running mask, then assert FEAT_ACTIVE reports them. RAM-only, not saved."""
    words = [0] * 8
    for f in feature_ids:
        words[f // 16] |= 1 << (f % 16)
    assert mb.write_multiple(10000, words) == 8
    assert mb.read_input(10016, 8) == words, "feature not ACTIVE (precondition)"
```

```python
# tests/test_daybreak_q1_fix.py
def test_q1_ir101_reports_max_cell_v_when_enabled(ours):
    daybreak_enable(ours.mb, DAYBREAK_F_Q1_FIX, DAYBREAK_F_BATT_DETAIL)
    ...
```

- Feature tests are **ours-only**, since there's no factory oracle for behaviour the
  factory doesn't have. They live in `tests/test_daybreak_<feature>.py` (sim) and
  `tests/test_daybreak_<feature>.c` (host), and `make test-daybreak` selects them.
- Each test sets **only** its own flags plus its `requires`, so the test shows its
  true dependency set.
- Coverage bookkeeping works as on the factory surface. A feature's IR/HR block gets
  a per-register file under `docs/wiring/ARM-UART5-dongle/` with a
  `## Test coverage` section, and `tools/reg_coverage.py` picks it up by filename.

### 6.3 What each feature must prove before it merges

These requirements attach to what a feature *does*. They aren't a tiering of
features.

| if the feature … | it must also have |
|---|---|
| *(every feature)* | an **enabled** test pinning the new behaviour; an **off ⇒ unmapped** test (its blocks give exception 2 with the bit clear) |
| drives a peripheral or keeps state | an **on → off ⇒ restored** test: enable, exercise, disable, then assert the parity behaviour returns within one tick |
| has `persist` registers | a **SAVE → reboot → same values** test, and a **no SAVE → reboot → defaults** test |
| changes any register below 10000, or any factory-visible behaviour | an **off == factory** oracle test (the same scenario on the factory image and on ours with the flag clear, both agreeing; usually an existing contract reused), plus a `docs/31` entry naming the quirk and recording "fixed behind Daybreak feature *n*" |
| commands the power path | a **lease expiry / link-quiet revert** test (docs/38 §1.4), and a **refused without authorization** test (§5 rule 7) |

### 6.4 Control-plane, store and chord tests (T28/T29)

- **host (`make test`)**:
  - mask validation: unknown bit, ID 0, `requires`, `conflicts` ⇒ exception 3
    with nothing applied;
  - SAVE, RELOAD and CLEAR;
  - snapshot packing (defaults omitted, sorted, multi-page);
  - torn-SAVE recovery (newest *complete* generation wins);
  - unknown-key carry;
  - range-invalid values fall back to the default;
  - ring wrap and erase-ahead.
- **sim, ours**:
  - block 0 answers with `"DAYB"`; blocks 1–24 give exception 2 with the mask zero;
  - a RAM-only enable is lost on reboot, and a SAVE'd one survives it;
  - the boot chords (§7), driven by holding the key inputs low at reset.
- **sim, factory**: pin §2.2 as a factory-only test (IR/HR 10000+ read `0`; a write
  to HR 10000 gets exception 2; the ARM stays alive). This is the discovery and
  safe-on-factory contract, and it flags any factory update that starts using the
  window.

## 7. Front-panel recovery chords

The wire is exactly the thing that might be broken when you need to recover, so
two power-on key chords give a local way out. They are part of the control plane:
always present in `ENABLE_DAYBREAK=1`, independent of the mask, and inert unless
keys are held at power-on. Chords are defined by **key role**. The pin behind each
role is the open item ⚠️ below.

| chord | how | effect |
|---|---|---|
| **Daybreak safe mode** | hold **UP + DOWN** through power-on until the LCD shows "Daybreak safe mode" (≥ 3 s) | This boot only: running mask forced to 0, `CTL_STATUS.safe_mode` set, and `FEAT_EN`/`FEAT_CMD` writes refused (exception 4) until the next reboot. The saved snapshot is untouched. The LCD then offers **ENTER** = also CLEAR the saved Daybreak state, **ESC** = keep it. |
| **Factory reset: all settings** | hold **ENTER + ESC** through power-on for ≥ 10 s until the LCD asks "Reset ALL settings?", then confirm with **UP, DOWN, UP, ENTER** within 10 s. Any other key, or a timeout, boots normally with nothing changed. | (1) every **factory** setting back to factory defaults, by the same routine HR 11 bit 1 `AlltoDefault` runs (T30); (2) Daybreak CLEAR plus erase of the settings ring and every feature-owned ring (§4.3, §4.5); (3) reboot. **Kept:** the serial number (HR 2-6, factory-provisioned identity the dongle and cloud bind to), energy/runtime counters and fault records. Those aren't settings and have their own HR 11 bits. |

Design notes:
- **A chord is exactly its two keys pressed and the other two released.** Any
  other pattern counts as no chord and boots normally, including all four pressed,
  which is what a disconnected panel ribbon, a shorted keypad or the emulator's
  default IDR looks like. "Held" is debounced and continuous for the whole
  interval. Releasing early cancels.
- The long hold plus the confirm sequence means a stuck key, a leaning object or a
  curious child can't wipe a configured installation. Safe mode is harmless, so it
  gets the short chord.
- The factory reset shares `settings_factory_reset()` with HR 11 bit 1, so "factory
  defaults" means the same thing from the wire and from the panel. Only the chord
  adds the Daybreak wipe.
- **HR 11 `AlltoDefault` over the wire also does a Daybreak CLEAR** (proposed). Then
  "factory defaults" from any source leaves the mirror. This is still to decide in
  T28, and it will be recorded in the docs/31 "OSS behaviour decisions" list.
- ⚠️ **Key-role ↔ pin mapping is inconsistent in the tree.** The authoritative
  wiring overview ([`docs/wiring/README.md`](wiring/README.md), "Front-panel keys")
  and [`docs/28`](28-factory-hmi.md) (dynamic, factory HMI) give **PC9 Up, PA8 Down,
  PA11 Enter, PC8 Esc**. `include/inv/keypad.h` assigns **PA8 UP, PA11 DOWN, PC8
  ENTER, PC9 ESC**. T28 must settle which is right, with an oracle test that drives
  each pin on the factory HMI, before binding chords to pins. Per AGENTS.md, the
  wiring file wins until then.
- Factory boot-key behaviour is unchecked. If the factory has its own power-on
  chord (for example into the "KEY/LCD Ageing Test" service screens), reusing the
  same chord would surprise users. T28 checks `sub_08016af0`'s boot-time callers
  first.

## 8. Interaction with the parity work

- Parity work (docs/39 P0–P3) **always takes precedence** and needs no flags. A
  behaviour the factory has is parity, so it goes in the trunk, ungated.
- If a feature uncovers a parity gap (the factory does X and ours doesn't), fix the
  gap in the trunk through the normal oracle-first loop, not inside the feature.
- A factory update that starts using any register ≥ 10000, or moves its battery
  bank, is caught by the factory-only test in §6.4. It's handled like any other new
  factory behaviour: parity first, and the Daybreak window moves if it must. That is
  one reason clients **must** discover through IR 10000 rather than assume.

## 9. Open items

| # | item | how to settle it |
|---|---|---|
| 1 | Does the real UART5 task answer IR/HR 10000+ like the USART3 slave (§2.2)? | T02 (RTOS in harness) or a bench capture |
| 2 | Does the stock dongle or cloud ever **write** outside HR 0–255? (A bulk write to unknown HRs could flip flags by accident.) | dongle-side capture of a cloud "settings" session; docs/26 shows the dongle is a transparent relay, so the question is what the cloud sends |
| 3 | Key-role ↔ pin mapping, and any factory power-on chord (§7) | T28 oracle test on the factory HMI |
| 4 | Exactly which fields factory `AlltoDefault` resets, and whether it keeps the SN | T30 oracle test |
| 5 | Does HR 11 `AlltoDefault` also CLEAR Daybreak? (proposed: yes) | decide in T28; record in docs/31 |
| 6 | Real chip size before using `0x020000+` for feature rings (docs/24 "size the chip at runtime") | T29 JEDEC `0x9F` check |
