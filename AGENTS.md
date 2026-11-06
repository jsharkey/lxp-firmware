# AGENTS.md — working agreement for agents (and humans) in this repo

This repo is a **collaborative reverse-engineering + reimplementation** effort
with **several agents working in parallel**, plus humans. These rules keep us
from tripping over each other. Read this before your first commit, and skim it
again at the start of each prompt.

If a prompt tells you to do something different, the prompt wins. Otherwise,
follow this.

## Git workflow

- **Commit directly to `main`.** Do **not** create working branches, and do
  **not** open pull requests. The history on `main` *is* the shared record of
  what's been learned.
- **Pull the latest `main` before you start each prompt, and read what changed.**
  Other agents have been working in parallel; their commits and docs may have
  already answered, moved, or reframed part of what you were just asked to do.
  So before going forward, skim the new commits and touched docs and let them
  update your plan — your prompt was written against an earlier `main`, and the
  current one may make some of it done, redundant, or wrong.

  ```bash
  git pull --rebase origin main   # before you start — then review what moved
  ```
- **Rebase (never merge) before you push**, so history stays linear and
  collisions surface early:

  ```bash
  git pull --rebase origin main   # again, right before pushing
  git push origin main
  ```
- **Commit message style** (match the existing log): `area: imperative summary`,
  e.g. `docs/30: trace the FW-version fields to their per-CPU source`,
  `firmware/tests: flow 0x359 bitfields to Modbus`, `hmi-sim: robust boot cache`.
- **Never force-push `main`** or rewrite shared history. If a rebase gets
  messy, stop and resolve it honestly rather than discarding others' commits.

## Don't stumble over each other

**The `docs/` numbering is the #1 collision point.** Docs are
`docs/NN-slug.md`, numbered roughly in discovery order. Two agents who both
grab "the next number" while offline will collide — this has already happened
(`10-`, `21-`, and `23-` each exist twice).

- Before creating a doc, **pull `main`** and pick the next free `NN` from the
  *current* `ls docs/` — not from memory, not from a number you reserved
  earlier.
- **If you rebase and find your number is now taken on `main`, you are the
  later arrival: renumber *your* file**, not the one already landed. Update the
  doc's `# Title` line if it references the number, fix every cross-reference
  (`docs/NN`) and the README links, all in the same commit. (See the existing
  "renumber to avoid collision" commits for the pattern.)
- **Cross-reference by slug in prose** where you can, and **always fix links
  when a file moves.** A dead `docs/NN` link is how the next agent gets lost.

**Coordinate through the README Status checklist** (`README.md`,
"Status: bootstrapping"). It is the shared roadmap:

- Pick an unchecked `[ ]` box or a `[~]` in-progress item to work on; scan the
  checklist *and recent commits* first so you don't redo work already in flight.
- When you finish something, **check its box and add the `docs/NN` link in the
  same commit** that lands the work. That's how the other agents see it's done.

**Hand-offs are a first-class pattern.** When your work depends on evidence you
can't reach yourself (another firmware image, a domain you can't run), write a
short hand-off doc that states *exactly* what's needed — see
`docs/17`, `docs/23`, `docs/30` for the established style. Don't block; pass the
baton.

## Never commit the proprietary images

The factory firmware binaries are **proprietary and must stay out of the tree.**
`.gitignore` already excludes `reference/*.bin`, `reference/*.hex`, `*.hex`, and
`.hmi_cache/`. (The flat image is named after its source `.hex`, e.g.
`reference/ceaa-07xx_vE_260214.bin` — the 07-series is the current reference.)

- **Never `git add -f`** any of those, and never paste large verbatim dumps of
  proprietary code/data into docs or source. Describe findings; cite addresses.
- The integrity record for those images is the hash table in `README.md` — keep
  it, don't replace it with the files.

## Build & test before you push

Run what's relevant to what you touched, and don't push red — **with one
deliberate exception** (see below):

```bash
make test        # host unit tests — always, if you touched src/ or include/
make test-sim    # GPIO/HMI behaviour tests — if you touched GPIO/HMI/emulator
make             # 12000XP build; add VARIANT=18kpv / VARIANT=6000xp if touched
```

- **Simulator tests may be committed red for *our* firmware** when they pass
  **green against the factory image**. The harness runs both firmwares (see
  `docs/19`), so a new `make test-sim` test that encodes proven factory
  behaviour is a valid spec to land even before our side implements it — that's
  the TDD target a later step makes green. Mark such a test clearly as a
  known-red-for-ours spec and say so in the commit. This exception is **only**
  for simulator tests; host `make test` and the builds must stay green.

- `tools/` are **read-only RE scripts** — they read the images in `reference/`
  and emit analysis; they do not modify firmware. Keep them non-destructive.
- If a test can't run because it needs a proprietary image you don't have, say
  so explicitly in your commit/notes rather than pretending it passed.
- **When a test exercises a dongle Modbus register, record it in that register's
  `## Test coverage` section** in [`docs/modbus-dongle/`](docs/modbus-dongle/README.md).
  Every `IR*`/`HR*` file carries one, listing the tests that cover each register
  and flagging the ones with no test yet. Keep it current as you add, rename, or
  retarget a test — link the test file and name the test function. That list is
  how we see, at a glance, where coverage is still thin; a test that isn't
  recorded there is coverage the next agent can't find.

## Claims discipline (this project lives or dies on it)

The whole corpus is scrupulous about **proven vs inferred vs guessed** — note
the `[x]`/`[~]`/`[ ]` markers, phrases like "proven", "both ends proven",
"pending the ARM image", and "corrects the docs/16 guess". Match that bar:

- Label findings by confidence and **cite the evidence**: function address
  (`FUN_...`/`sub_...`), the tool used, which image/variant, static vs dynamic.
- **Don't upgrade a hypothesis to a fact.** "Dynamic capture on both ends"
  outranks "two static enumerations agree" outranks "plausible from strings".
- When you **correct** an earlier doc, say so and leave a pointer from the old
  doc to the new finding — don't silently diverge. The next agent will trust
  what's written.

## Authoritative references — and keep them current

Some knowledge has outgrown a single numbered doc and now lives in a **curated
`docs/` subdirectory** that is the **source of truth** for its domain. The
numbered `docs/NN-*.md` are the *research trail* (how we figured something out,
in discovery order); these subdirs are the *distilled, reconciled result*. When
a numbered doc and a subdir file disagree, **the subdir file wins.**

| domain | authoritative source | holds |
|---|---|---|
| **Inter-processor & external protocols; hardware IO** | [`docs/wiring/`](docs/wiring/README.md) | one file per physical link (`ARM-USART3`, `DSP-SCI-C`, …): ports, **pins**, electrical type, baud, framing, direction; the overview carries the system block diagram + the full ARM pin map |
| **The external dongle Modbus registers** | [`docs/modbus-dongle/`](docs/modbus-dongle/README.md) | one file per register/group (`IR001-Vpv1`, `HR022-StartPVVolt`, …): meaning, scaling, and where each input's data **comes from** / each write's **side-effects**; the README indexes the whole spec surface |

**When your work touches one of these domains, update the relevant file there —
don't just drop the finding in a numbered doc or a commit message.** If you pin a
new pin, decode a frame field, trace where an input register's value originates,
or find a holding register's side-effect, the matching `docs/wiring/` or
`docs/modbus-dongle/` file is where it belongs (add a numbered doc too if the
*derivation* is worth recording, and link the two). A finding that never reaches
the authoritative file is invisible to the next agent.

- These files are **named, not numbered**, so they sidestep the `docs/NN`
  collision problem — edit the right existing file rather than creating a new
  numbered one.
- Scope discipline matters in `docs/modbus-dongle/`: it is **only** the dongle
  Modbus surface. The internal links (ARM↔DSP, safety-CPU, MPPT) are different
  wires with different framing — document those in `docs/wiring/`, and keep the
  distinction (see that README's "four EG4-Modbus-family links" note).
- Each `docs/modbus-dongle/` register file has a `## Test coverage` section; when
  you write or change a test that touches a register, update that section (see
  **Build & test** above).
- Leave a breadcrumb: when you move a fact into one of these subdirs, point the
  old numbered doc at it (the existing "Authoritative wiring:" / "Dongle
  registers:" banners are the pattern).

## Record factory quirks (they may be bugs to fix)

When you notice the factory firmware doing something **unexpected** — behaviour
that deviates from the published spec (the EG4 Modbus doc, the CAN/BMS contract,
a datasheet), is internally inconsistent, or just looks wrong — **write it down
in [`docs/31-factory-quirks.md`](docs/31-factory-quirks.md)**, the running
catalogue. Don't leave it buried in a commit message or a sub-finding of another
doc where the next agent won't find it.

Why this matters: we reimplement **functionally**, not byte-for-byte, so a
factory quirk is a decision point, not something to copy by reflex. Each one is
potentially a **bug we can fix** in the open-source firmware — but only if it's
recorded so we can decide deliberately.

For each quirk note: **what** the factory does, **what** the spec/expectation
was, the **evidence** (function address / tool / which image), and a **verdict**
— replicate it (it may be load-bearing: another peer or the protocol may depend
on the quirk), fix it in our firmware, or still-to-decide. Never silently "fix"
a quirk you only assume is a mistake; flag it in `docs/31` and let the call be
explicit.

## Orientation

- `README.md` — scope, strategy, status checklist, build matrix. Start here.
- `docs/` — the recovered specification (research trail); `docs/01` and `docs/02`
  are the baseline.
- **`docs/wiring/`** — authoritative: protocols, links, hardware IO/pins.
- **`docs/modbus-dongle/`** — authoritative: the external dongle Modbus registers.
- `include/inv/` — the recovered data model (states, faults, settings,
  modbus_map, hmi_menu, variant). Source of truth for the reimplementation.
- `src/` — the GCC skeleton firmware (modbus / uart / can / hmi / dsp).
- `tests/`, `tools/` — host tests and the Unicorn emulator / on-screen HMI.
