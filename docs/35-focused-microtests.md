# Focused micro-tests — narrow factory-vs-ours, without a full boot

The full-simulator suite (`make test-sim`, `tests/test_arm_sim.py`) is our most
valuable correctness tool: it runs the **same black-box test code against both
the factory image and our firmware**, booting each and reaching behaviour over
the real interfaces. But a full boot + Modbus round-trip is expensive, and it
only gets more so as the harness grows. For logic that lives in a **single, pure
function**, we don't need the whole machine.

This doc describes a cheaper, complementary pattern — a **focused micro-test** —
and uses the **AC-First time-window** evaluator as the worked example
(`make test-window`). It keeps the thing we care about most: *the same test
vectors judge the factory and our firmware.*

## The idea

Pick a narrow piece of behaviour that is a pure function of a little state
(here: "is the current clock inside any AC-First window?" — a function of the
three window registers + the time). Then drive **only that function**, two ways,
from **one set of vectors**:

```
            tests/timewindow_contract.py   (VECTORS + two backends)
                         │
      ┌──────────────────┴───────────────────┐
  OursBackend                            FactoryBackend
  Unicorn → our firmware's               Unicorn → the factory ARM
  acfirst_window_active()                evaluator, called in isolation
  by SYMBOL from the ELF                 (only RTC + window regs seeded)
      │                                        │
      └──────────────→ test_timewindow.py ←────┘
             same VECTORS assert both; and that they AGREE
```

**Both backends use the same strategy** — load an ARM image into Unicorn
(`tools/emu.py`) and call **one function in isolation**, no boot:

- **OursBackend** loads our built firmware (`build/firmware.bin`), resolves
  `acfirst_window_active` **by symbol** from `build/firmware.elf` (not a
  hard-coded address — it shifts between builds), writes the window registers to
  scratch RAM, and calls it through the real ARM calling convention (`r0` = regs
  pointer, `r1` = n windows, `r2` = now-minutes), reading the verdict from `r0`.
  So our code is exercised exactly as the firmware runs it, not as host x86.
- **FactoryBackend** loads the factory image and calls **just the evaluator
  function**, with only the RAM it reads seeded (the RTC bytes + the window-config
  registers, plus any enable gate) — the isolated-call recipe proven in
  `tools/emu_acfirst.py`, reduced to a reusable function.

Because both answer the same `active(windows, hour, minute) → bool` question
through the same mechanism, the test body is identical, and a third test asserts
the factory **oracle** and our firmware agree on every vector.

> Needs `pip install unicorn` and a built firmware (`make`); the host-only,
> toolchain-free coverage of the pure function stays in `tests/test_acfirst.c`.

## How our firmware surfaces a testable interface

The enabling move is on our side: **extract the logic into a pure, transport-
agnostic function** with no I/O and no globals, so it can be called from a host
test (and from `main.c` in the real loop). For AC-First that is already done:

```c
/* include/inv/acfirst.h */
bool acfirst_window_active(const uint16_t *regs, int n, uint16_t now_min);
```

It takes the window registers and minutes-of-day and returns the verdict —
nothing else. `main.c` wires it to the register image and surfaces the result as
IR 126 bit 8; the tests call it directly. The same shape (a pure evaluator taking
the relevant registers + the clock) is what makes a feature micro-testable.

## Running it

```bash
make test-window                          # builds our firmware, then runs both halves
python3 tests/test_timewindow.py IMG.bin  # point at a factory flat .bin
```

- The **ours** half needs `unicorn` + a built firmware (`make`); `make
  test-window` builds it first. It must stay green.
- The **factory** half additionally needs a factory image (proprietary, never
  committed — see the README hash table). When it runs,
  `test_acfirst_factory_agrees_with_ours` / `..._acchg_...` are the payoff: a
  direct factory-vs-ours equivalence check on the narrow logic.
- Each half **skips cleanly** when its prerequisites are absent (so CI without
  unicorn, the toolchain, or the image stays green rather than failing).

This suite is **separate from `test` and `test-sim`** — it adds coverage without
touching the existing ones.

## Per-image addresses (auto-detected)

The factory evaluator and the RAM it reads live at **different addresses in
different images**. `tests/timewindow_contract.py` keeps a `PROFILES` table and,
by default (`profile="auto"`), **identifies the right one by probing** the image
(the profile whose evaluator reads active at 07:00 and inactive at 09:00 for a
06:00-08:00 window). So `make test-window` works for either image with no flag;
`--profile` forces one.

| profile | image | evaluator | RTC | windows | status bit | verified |
|---|---|---|---|---|---|---|
| `ceaa05` | `reference/ceaa-05xx_com_vE_250325.bin` (05-series) | `0x0801ece8` → `sub_0801eb4c` | `0x2000a718` (+1 min, +2 hr) | `0x20009854+0x64` | bit 24 of `0x2000a758` | via `tools/emu_acfirst.py` |
| `ceaa07` | ceaa-07xx (07-series) | `sub_080352d0` | `0x2000d850` | `0x2000c85c+0x64` | bit 24 of `0x2000d890` | **✔ green on `ceaa-07xx_vE_260214`** |

## Does the AC-First evaluator test any other windows? No — but there's a family.

`sub_080352d0` reads RTC `+1`/`+2` (minute, hour) and **exactly the three
AC-First window pairs** (config `+0x64/+0x66`, `+0x68/+0x6a`, `+0x6c/+0x6e` =
HR 152-157) — and no other config offset (proven by tracing its config reads). So
it evaluates all **three** AC-First windows and nothing else.

The *other* schedules each have their **own** evaluator with the same structure.
They were found by scanning the image for the evaluator fingerprint — a
`now = 60*hour + minute` computation (`movs rX, #0x3c` + `mla`) — and reading the
config offset each then loops over (3 windows, 4-byte stride):

| evaluator | window cfg | result | feature | wired? |
|---|---|---|---|---|
| `sub_080352d0` | `0x2000c85c+0x64` | statusbit `0x2000d890`.24 | **AC-First** (HR 152-157) | ✔ `acfirst` |
| `sub_08034590` | `0x2000c85c+0x3a` | mask byte `0x2000dbb7` | **AC-charge** (HR 68-73), gated by ACChargeType (config `+0x33` bits 1-3) | ✔ `acchg` |
| `…@0x080349ba` | `0x2000cd5c+0x70` | mask byte `0x2000dbb8` | a slot-5 schedule (charge-priority / forced-discharge — identify) | ○ open |

(A fourth `now=60*h+m` site, `0x08032118`, has no window loop — a clock getter,
not an evaluator.)

> **Correction.** An earlier draft of this doc named `sub_0801d8dc` as the
> AC-charge evaluator. That is wrong: `sub_0801d8dc` is the **holding-register
> getter** (a big switch that *returns* HR 68-73 values), and `sub_080241a8` is a
> settings-change detector — neither compares windows to the clock. The real
> AC-charge evaluator is **`sub_08034590`** (now wired).

## Wiring an evaluator (the AC-charge worked example)

Evaluators are listed per **window type** in `EVALUATORS` (each with image
variants, auto-probed). AC-charge (`sub_08034590`) was added by:

1. **Find it** — scan for the `now=60*h+m` fingerprint; note the window config
   offset (`+0x3a`) and the per-window result byte (`0x2000dbb7`), e.g. by
   diffing RAM in-window vs out.
2. **Its enable gate** — unlike AC-First, it exits early unless
   **ACChargeType ≠ 0** (config `+0x33` bits 1-3); the spec seeds `enable=(0x33,
   0x02)` ("by time"). (It is otherwise self-contained, so `Emu.call()` works.)
3. **Reuse the oracle** — our `acfirst_window_active()` is a **generic**
   start-incl/end-excl/wrap predicate, so it is the oracle for *every* window
   type. The **same VECTORS** run against it and the factory AC-charge evaluator;
   `test_acchg_factory_agrees_with_ours` passing proves AC-charge shares AC-First's
   window semantics.

The test body never changes; only the `EVALUATORS` entry + (shared) vectors do.
Still open: the slot-5 evaluator above. **OptimalChg (HR 126-131) is resolved:
it is a dormant table in ceaa-07xx** — stored and read-back but never evaluated
against the clock or pushed to the DSP (only the config clear/getter/setter touch
its RAM; a runtime read-hook and a full-RAM / DSP-config sweep find no evaluator).
So it gets no `EVALUATORS` entry; its only black-box coverage is the dongle
store/read-back round-trip (`test_modbus_optchg_table_roundtrip`) and the pure
`optchg_slot_mode()` host test. See
[`docs/31` Q5](31-factory-quirks.md) and
[`docs/modbus-dongle/HR126_131`](modbus-dongle/HR126_131-OptimalChg_DisChg.md).

See also: [`docs/25`](25-modbus-register-spaces.md) (the AC-First observable and
the IR 126 funnel), [`docs/19`](19-gpio-test-harness.md) (the full-sim harness
this complements).
