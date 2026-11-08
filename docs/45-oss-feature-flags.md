# 45 — Feature flags: how OSS features land without disturbing factory parity

**Status: design, adopted as the plan of record; nothing here is implemented yet.**
The work to build it is task **T28** in [`docs/39`](39-parity-roadmap.md). The
register allocation is authoritative in
[`docs/wiring/ARM-UART5-dongle/registers.md`](wiring/ARM-UART5-dongle/registers.md)
("Address-space allocation"). The control-plane registers are
[`HR10000_10039-OSS-feature-control.md`](wiring/ARM-UART5-dongle/HR10000_10039-OSS-feature-control.md)
and [`IR10000_10039-OSS-capability.md`](wiring/ARM-UART5-dongle/IR10000_10039-OSS-capability.md).
The feature *ideas* are in [`docs/38`](38-oss-feature-ideas.md). This doc says how
any of them gets built.

## The problem

Most of the effort in this repo has gone into one property: **our firmware behaves
like the factory `ceaa-07xx` image**. That property is pinned by the oracle-first
suites: `make test`, `make test-sim`, `make regsweep`, `make wrsem`, the
cross-image persistence tests, and the rest ([`docs/39`](39-parity-roadmap.md)).
The features in docs/38 deliberately change behaviour. Some only add data, some
fix factory quirks, and some drive relays. If they land as ordinary code, each one
erodes that property a little, and after a dozen of them nobody can say which
behaviour is the factory's and which is ours.

## The rule

> **Out of the box, our firmware is the factory mirror.** With every feature flag
> clear (the default, and the state after a fresh flash or a flag reset), it must
> pass every existing parity test unchanged, and it must answer every register
> outside the OSS control block exactly as it does today. A feature changes
> behaviour **only** while its flag is set.

Everything below is how we enforce that rule mechanically, so it does not depend
on reviewers noticing.

---

## 1. Two layers of gating

| layer | what it is | who sets it | default |
|---|---|---|---|
| **Build-time: `OSS=`** | `make OSS=0` compiles **every** feature out, *including* the control block. That is the pure-mirror build. `make` (`OSS=1`) compiles the supported features in, gated off at runtime. | the builder | `OSS=1` (compiled in, runtime-off) |
| **Run-time: the feature-enable mask** | one bit per feature in **HR 10000–10007** (128 feature IDs). Writable over the dongle bus, persisted in the OSS flash region ([`docs/24`](24-oss-settings-region.md)). | the user / HA / a test | **all zero** |

Why both layers:
- The **build flag** is how we prove the rule cheaply. CI builds both `OSS=0` and
  `OSS=1` and runs the whole existing suite against each. If they diverge with the
  mask at zero, a feature leaked out of its gate. (§5.1)
- The **runtime mask** is what users and tests actually touch. One firmware image
  covers every combination, with no per-feature builds and no reflashing to
  try a feature.

A compile-time *default mask* (`make OSS_DEFAULT_MASK=…`) is allowed for **bench
builds only**, for example to have the bug-report recorder (docs/38 §6.1) armed
from first power-on during hardware bring-up. Release builds and every CI parity
job use the zero default, and the build prints a warning when the default is
non-zero.

## 2. The register surface (summary; the per-register files are authoritative)

All addresses are raw 0-based protocol addresses, as everywhere in this tree. They
are not Modicon `3xxxx`/`4xxxx` notation.

### 2.1 Where the OSS window sits, and why there

The OSS window is **IR 10000–10999 and HR 10000–10999**, 25 blocks of 40 registers
each, aligned to the dongle query groups (10000 = 250 × 40). An earlier draft
(docs/38 §2) proposed 1000–1399. We moved the window because the factory's own
register space is visibly still growing and 1000 left too little room:

| evidence | what it shows |
|---|---|
| spec PDF | IR up to 152, HR up to 198 |
| live 12000XP capture ([`docs/34`](34-multi-battery-can.md), `tools/lxp_pcap.py --reg 127`) | the factory serves **non-zero IR 174, 193–194, 199–200, 203–204**. Those are beyond-spec registers, already in use. |
| same capture | the dongle uploads **IR 0–380** and **IR 5000–5126** every cycle, so the cloud already *reads* to IR 380 |
| factory read path `sub_0801ef68` ([`docs/44`](44-dongle-modbus-crash-surface.md)) | it rejects HR reads landing in **4095–4999** and table-serves the battery bank from **5000**. The vendor's own address plan therefore runs to at least ~5000. |

So the factory's namespace is treated as **0–9999** in both spaces (the full
allocation table is in `registers.md`). Ours starts at 10000, past every number
the factory references, with a reserved OSS growth band 11000–19999 behind it.

### 2.2 What the factory does with that window (proven, dynamic)

Measured on `ceaa-07xx_vE_260214` under the harness (USART3 register slave,
`ModbusDsp`, both the `regsweep_contract` and `settings_contract` factory backends,
2026-11-08):

| probe | factory result |
|---|---|
| read IR/HR 10000–10007, 10039–10046, 20000, 32768 | **served, all `0`** |
| write-single HR 10000 (values 0 and 1), HR 10016 | **exception 2**, nothing stored (read-back `0`) |
| write-multiple HR 10000 ×4 | no echo, read-back `0` |
| HR 21 after all of the above | still answers (ARM alive) |

This gives us two properties for free:
- **Discovery.** A client reads IR 10000–10001. The factory returns `0,0`; ours
  returns the magic (§2.3). There is no guessing, and probing the factory this way
  has no side-effects.
- **Safe on the factory.** A client that writes feature flags to a unit running
  factory firmware gets exception 2 and nothing changes. A stale HA config can't
  harm a unit that was flashed back to factory.

⚠️ Caveat: this is the factory's **USART3** register slave, the harness oracle. The
real UART5 dongle task (`sub_0802afe2`) can't run in the harness yet (T02). The two
share the read/write server audited in docs/44, so the same answer is expected,
but it is **~ inferred** for UART5 until T02 or a bench capture confirms it.

### 2.3 Block 0, the control plane (always on when `OSS=1`)

Block 0 is the **only** part of the OSS window that answers while the mask is zero.
It holds no feature behaviour. It just lets a client find out what exists and
switch it on.

| reg | name | summary |
|---|---|---|
| **IR 10000–10001** | `OSS_MAGIC` | `0x4C58 0x4F53` (`"LXOS"`). The factory reads `0,0`. |
| IR 10002 | `OSS_SCHEMA` | register-schema version, `major<<8 \| minor` |
| IR 10003 | `OSS_CTL_STATUS` | safe-mode boot, mask-dirty, last-write-rejected, save-failed bits |
| IR 10008–10015 | `FEAT_SUPPORTED[0..7]` | features compiled into this build *and* applicable to this variant |
| IR 10016–10023 | `FEAT_ACTIVE[0..7]` | features enabled **and** whose dependencies/runtime preconditions hold |
| IR 10024–10031 | `FEAT_SAVED[0..7]` | the mask stored in flash (what the next boot will load) |
| **HR 10000–10007** | `FEAT_EN[0..7]` | **the feature-enable mask** (running). Write it to turn features on or off. |
| HR 10008–10015 | — | reserved for mask growth to 256 IDs |
| HR 10016 | `FEAT_CMD` | `0x5341` SAVE running→flash · `0x524C` RELOAD flash→running · `0x434C` CLEAR running+flash to zero |

Bit numbering: **feature ID *n* is bit `n % 16` of word `n / 16`**, in every
mask. Each mask word is a plain 16-bit register. The masks are deliberately not
32-bit pairs, so the dongle's reversed-word-order rule for pairs never applies.

The full semantics, including atomicity, validation and exception codes, are in
the two per-register files.

### 2.4 Feature blocks

Each feature that needs registers gets one or more 40-register **blocks** *k*
(1–24) at **10000 + 40·k**, in **both** spaces. The feature's telemetry goes on the
IR side and its settings and commands on the HR side, at the same block number.
So "feature X lives in block 5" means IR 10200–10239 and HR 10200–10239.

**While a feature is not ACTIVE, its blocks answer exactly as unmapped registers
do today: exception 2 for reads and writes.** Turning a feature off therefore
returns its corner of the address space to today's behaviour too.

## 3. Feature registry

The registry is a table: feature ID → name, class, block(s), dependencies,
conflicts, docs/38 section, status. It lives in `include/inv/oss_features.h` (to be
written in T28) as the single source of truth. The firmware uses it for
validation and the tests use it for preconditions. This doc carries the
human-readable copy below. Rules:

- **IDs are permanent.** When a feature is retired, its bit becomes a tombstone
  that is never reused. A client holding an old mask must never switch on
  something different.
- **An ID is frozen when its first implementation commit lands**, not before.
  The rows below are **proposals** (⬜). Claim one in docs/39 the usual way and
  flip it to 🚧, then ✅.
- **ID 0 is reserved** and is never a feature. A mask word of `0x0001` is
  therefore always an error, which catches clients that confuse "on" with
  "bit 0".
- **One behaviour per bit.** Don't build a "fix all quirks" bit. Q1 and Q2 get
  separate bits, so a user can take one fix without the other, and a failing test
  points at exactly one change.

### 3.1 Feature classes

The class decides how much proof a feature needs before it merges.

| class | meaning | factory-surface effect | extra proof required (§5.3) |
|---|---|---|---|
| **A: observe** | adds OSS **read-only** registers | none | off ⇒ its blocks exception 2 |
| **B: augment** | adds OSS settings or behaviour that act only through OSS registers or ARM-local peripherals (LED ring, LCD, fan curve, framing) | none on registers; may change physical behaviour | off ⇒ the peripheral is back under the parity code path |
| **C: deviate** | changes a **factory-surface** register value or factory-visible behaviour (quirk fixes, the dormant HR 126-131 scheduler) | **yes** | must cite its `docs/31` quirk/verdict; an **off == factory** oracle test; an **on** test that pins the new behaviour |
| **D: actuate** | remotely commands the power path (smart port, generator contact, setpoint overrides) | **yes** | everything in C, plus docs/38 §1.3–1.4 (envelope-only, **lease** with TTL) and depends on the write-authorization feature |

### 3.2 Proposed IDs (initial allocation; ⬜ = proposed, not frozen)

| ID | feature (docs/38 §) | class | blocks | requires |
|---|---|---|---|---|
| 0 | *reserved, never a feature* | — | — | — |
| 1 | ⬜ identity & health: git hash, build, uptime, reset reason (§3.1) | A | 1 | — |
| 2 | ⬜ bug-report flight recorder + func `0x65` (§6.1) | A | 2 | — |
| 3 | ⬜ relay / actuator state (§3.2) | A | 3 | — |
| 4 | ⬜ derived & high-resolution electrical (§3.4) | A | 4 | — |
| 5 | ⬜ windowed statistics (§3.5) | A | 5 | — |
| 6 | ⬜ link-health counters (§3.6) | A | 6 | — |
| 7 | ⬜ battery detail: per-pack / cell / `0x35A` alarms, Q3 (§3.3) | A | 7–9 | — |
| 8 | ⬜ safety-CPU vs DSP cross-check view (§3.7) | A | 10 | — |
| 9 | ⬜ timestamped event journal (§3.8) | A | 11 | — |
| 10–15 | *spare, class A* | | | |
| 16 | ⬜ write authorization / remote-control unlock (§5.4) | B | 12 | — |
| 17 | ⬜ standard Modbus RTU framing (§5.3) | B | — (mode in block 12) | — |
| 18 | ⬜ epoch / UTC-offset clock (§5.5) | B | 13 | — |
| 19 | ⬜ RGB LED-ring modes (§4.8) | B | 14 | — |
| 20 | ⬜ fan curve / acoustic (§4.6) | B | 15 | — |
| 21 | ⬜ LCD / buzzer niceties (§4.7) | B | 16 | — |
| 22–31 | *spare, class B* | | | |
| 32 | ⬜ Q1 fix: IR 101 from `0x373` max-cell-V (§7) | C | — | 7 |
| 33 | ⬜ Q2 fix: IR 97 real capacity (§7) | C | — | 7 |
| 34 | ⬜ Q5: honour the dormant HR 126-131 table (§4.4) | C | 17 | — |
| 35–47 | *spare, class C* | | | |
| 48 | ⬜ Smart Port direct control (§4.1) | D | 18 | 16 |
| 49 | ⬜ generator / dry-contact control (§4.2) | D | 19 | 16 |
| 50 | ⬜ dynamic charge/discharge setpoint overrides (§4.3) | D | 20 | 16 |
| 51–63 | *spare, class D* | | | |
| 64–127 | *unallocated* | | blocks 21–24 + the 11000–19999 band | |

The ID ranges per class are a filing convention, so a glance at a mask tells you
how risky it is: anything above bit 31 touches factory-visible behaviour. They are
not a hard rule. If a class overflows, take IDs from 64+.

### 3.3 Dependencies, conflicts and preconditions

- **`requires`**: a mask that sets a feature without its prerequisites is
  **rejected whole** with exception 3. The firmware doesn't auto-enable the
  prerequisite, because a client should never end up with a feature it didn't ask
  for.
- **`conflicts`**: two features that can't run together (for example two owners
  of the LED ring). Same treatment: exception 3, nothing applied.
- **Runtime preconditions** are things like "the variant has this hardware",
  "the DSP link is up" or "the unit is in standby". A feature can be **enabled
  but not ACTIVE**. `FEAT_EN` records what was asked for and `FEAT_ACTIVE` reports
  what is actually running. Tests and clients must check `FEAT_ACTIVE`, not
  `FEAT_EN`.

## 4. Code rules for a feature

These are reviewable rules. T28 adds a lint for the first two.

1. **One gate function.** Every feature entry point checks
   `oss_feat_active(OSS_F_<NAME>)`. That is a single inlined bit test against the
   ACTIVE mask, read once per scheduler tick. No feature code runs on any other
   condition. With `OSS=0` the macro folds to constant `0` and the compiler
   discards the feature.
2. **Features live in `src/oss/`**, one file per feature, plus the control plane
   `src/oss/oss_features.c`. The parity trunk (`src/modbus`, `src/bms`, `src/sched`,
   …) gets **hooks** and never feature bodies. A hook is the narrowest possible
   seam. For example the IR getter does
   `v = factory_value(); if (oss_feat_active(OSS_F_Q1_FIX)) v = oss_q1_ir101(v);`.
   The factory computation always runs and stays testable. The feature only
   overrides the output.
3. **Parity code never reads a feature's state.** Information flows one way only:
   from the trunk to the feature. A trunk module that starts branching on OSS
   settings is a review failure.
4. **Off means off within one tick.** When a feature's bit clears, or its
   preconditions drop, it must within one scheduler tick release every lease it
   holds, return every peripheral it drove to trunk control, and stop changing any
   factory-surface value. Its OSS settings stay saved for the next enable.
5. **Own settings in the OSS region only.** A feature never writes the factory
   config slots differently from what the trunk would write ([`docs/24`](24-oss-settings-region.md)).
   A unit flashed back to factory firmware must not be able to tell a feature ever
   ran.
6. **No new factory-surface register values outside class C/D.** A class A or B
   feature that needs to change an IR/HR below 10000 has been misclassified.
7. **The safety envelope doesn't move** (docs/38 §1.3). No flag can unlock values
   outside what the factory HMI accepts.

### 4.1 Persistence and the escape hatches

- **Boot:** running mask ← saved mask (zero when no valid OSS record exists, so a
  fresh flash or a flash-back-and-forth always boots as the mirror).
- **A write to `FEAT_EN` is RAM-only** until `FEAT_CMD = SAVE`. Trying a feature is
  therefore always undone by a power cycle. That is the main safety net on real
  hardware: a feature that wedges something is gone after a reboot, unless someone
  deliberately saved it.
- **`FEAT_CMD = CLEAR`** zeroes both the running and the saved mask, returning the
  unit to the mirror state over the wire.
- **Front-panel safe mode** (proposed, T28 picks the key chord): holding a chord at
  power-on boots with the running mask forced to zero and sets
  `OSS_CTL_STATUS.safe_mode`. That is the recovery path when the wire is the thing
  that broke.
- **HR 11 `AlltoDefault`** (factory reset) also clears the OSS mask and the OSS
  settings. A user who says "factory defaults" gets the mirror. This is a
  deliberate decision and gets its own docs/31-style note when T28 lands.

### 4.2 Who may write the flags

The flags are as writable as any factory setting. The dongle, the cloud behind it,
and any RS-485 master can write HR 10000 just as they can write HR 21 or reboot the
unit with HR 11 (docs/31 Q14). That is acceptable for class A–C, which change
nothing the factory surface doesn't already let a master change. **Class D
features additionally require feature 16 (write authorization) to be ACTIVE**, and
feature 16 adds a front-panel "remote control: allow" gate (docs/38 §5.4). So a
remote master can't grant itself actuation.

## 5. Testing strategy

### 5.1 The parity gate: existing tests, untouched

- The **entire existing suite runs on the default build with the mask at zero,
  unmodified.** No existing test may be edited to know about flags. If a parity
  test needs editing because of a feature, the feature leaked out of its gate.
- CI (and `make test-parity`, added in T28) builds **`OSS=0`** and **`OSS=1`** and
  runs `make test`, `make test-sim`, `make regsweep` and `make wrsem` against both.
  The two must produce identical verdicts. The one expected difference is
  `regsweep`'s view of block 0, which isn't in its sweep range (IR 0-159, HR 0-255,
  IR 5000-5126) anyway.
- A sim test boots fresh from an **erased OSS region**, so the saved mask is zero.
  Any test fixture that reuses a flash image across tests must clear the OSS
  region (or send `FEAT_CMD = CLEAR`) between tests, so a feature test can never
  leak flags into a parity test.

### 5.2 Feature tests: flags as a precondition

Every feature test **turns on exactly the flags it needs as its first step** and
asserts that they took effect:

```python
# tests/oss_helpers.py  (T28)
def oss_enable(mb, *feature_ids):
    """Precondition: set exactly these features (and nothing else) in the
    running mask, then assert FEAT_ACTIVE reports them. RAM-only, not saved."""
    words = [0] * 8
    for f in feature_ids:
        words[f // 16] |= 1 << (f % 16)
    assert mb.write_multiple(10000, words) == 8
    assert mb.read_input(10016, 8) == words, "feature not ACTIVE (precondition)"
```

```python
# tests/test_oss_q1_fix.py
def test_q1_ir101_reports_max_cell_v_when_enabled(ours):
    oss_enable(ours.mb, OSS_F_Q1_FIX, OSS_F_BATT_DETAIL)
    ...
```

- Feature tests are **ours-only**. No factory oracle exists for behaviour the
  factory doesn't have. They live in `tests/test_oss_<feature>.py` (sim) and
  `tests/test_oss_<feature>.c` (host), and are named so `make test-oss` can select
  them.
- Each feature test sets **only** its own flags plus its `requires`. That way a
  test shows its true dependency set.
- Coverage bookkeeping is the same as for the factory surface. A feature's IR/HR
  block gets a per-register file under `docs/wiring/ARM-UART5-dongle/` with a
  `## Test coverage` section, and `tools/reg_coverage.py` picks it up by
  filename.

### 5.3 What each feature must prove before it merges

| test | A | B | C | D |
|---|---|---|---|---|
| **enabled**: the new behaviour, pinned | ✔ | ✔ | ✔ | ✔ |
| **off ⇒ unmapped**: its blocks return exception 2 when the bit is clear | ✔ | ✔ | ✔ | ✔ |
| **on → off ⇒ restored**: enable, exercise, disable, and assert the parity behaviour is back within one tick | | ✔ | ✔ | ✔ |
| **off == factory oracle**: the same scenario against the factory image, the C/D feature with its flag clear on ours, and both agree. Usually this is an existing contract reused. | | | ✔ | ✔ |
| **lease expiry / link-quiet revert** (docs/38 §1.4) | | | | ✔ |
| **refused without feature 16 / front-panel allow** | | | | ✔ |
| **docs/31 entry** names the quirk and records "fixed behind flag *n*" | | | ✔ | (if it fixes a quirk) |

### 5.4 Control-plane tests (T28)

- **host (`make test`)**: mask validation (unknown bit, ID 0, `requires`,
  `conflicts` ⇒ exception 3 and nothing applied); SAVE/RELOAD/CLEAR; boot from
  erased, valid and corrupt OSS records; ACTIVE ⊆ EN ∩ SUPPORTED.
- **sim, ours**: block 0 answers with the magic; blocks 1–24 return exception 2
  with the mask zero; a RAM-only enable is lost on reboot and a SAVE'd one
  survives it.
- **sim, factory**: pin §2.2 as a factory-only test (IR/HR 10000+ read `0`, a write
  to HR 10000 gets exception 2, and the ARM stays alive). This is the discovery and
  safe-on-factory contract, and it alerts us if a factory update ever starts using
  the window.

## 6. Interaction with the parity work

- Parity work (docs/39 P0–P3) **always takes precedence** and doesn't need flags.
  A behaviour the factory has is parity, so it goes in the trunk, ungated.
- If a feature uncovers a parity gap (the factory does X and ours doesn't), fix the
  gap in the trunk under the normal oracle-first loop. Don't fix it inside the
  feature.
- A factory update that starts using any register at or above 10000, or that moves
  its battery bank, is caught by the factory-only test in §5.4 and handled like any
  other new factory behaviour: parity first, and the OSS window moves if it has to.
  That is one reason clients **must** discover through IR 10000 rather than assume.

## 7. Open items

| # | item | how to settle it |
|---|---|---|
| 1 | Does the real UART5 task answer IR/HR 10000+ the same way as the USART3 slave (§2.2)? | T02 (RTOS in harness) or a bench capture |
| 2 | Does the stock dongle/cloud ever **write** outside HR 0–255? (If it bulk-wrote to unknown HRs, flags could flip by accident.) | dongle-side capture of a cloud "settings" session; docs/26 shows the dongle is a transparent relay, so the question is what the cloud sends |
| 3 | Front-panel safe-mode key chord | T28, against the keypad map ([`docs/06`](06-hmi.md)) |
| 4 | Does HR 11 `AlltoDefault` clearing OSS state need an opt-out? | decide in T28; record in docs/31 |
