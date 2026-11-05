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
  ctypes → our compiled                  Unicorn → the factory ARM
  acfirst_window_active()                evaluator, called in isolation
  (src/sched/acfirst.c)                  (only RTC + window regs seeded)
      │                                        │
      └──────────────→ test_timewindow.py ←────┘
             same VECTORS assert both; and that they AGREE
```

- **OursBackend** compiles `src/sched/acfirst.c` into a tiny shared library and
  calls `acfirst_window_active()` through `ctypes`. No emulator, no ARM
  toolchain — just the host `cc` that `make test` already needs. This is the
  TDD loop for our firmware: red until the pure function is right, green after.
- **FactoryBackend** loads the factory image into Unicorn and calls **just the
  evaluator function**, with only the RAM it reads seeded (the RTC bytes and the
  window-config registers) — no boot, no scheduler, no peripherals beyond what
  `tools/emu.py` already stubs. This is the exact isolated-call recipe proven in
  `tools/emu_acfirst.py`, reduced to a reusable function.

Because both backends answer the same `active(windows, hour, minute) → bool`
question, the test body is identical, and a third test asserts the factory
**oracle** and our firmware agree on every vector.

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
make test-window                          # ours always; factory if available
python3 tests/test_timewindow.py IMG.bin  # point at a factory flat .bin
```

- The **ours** half runs everywhere and must stay green.
- The **factory** half **skips cleanly** when `unicorn` is not installed or no
  factory image is present (the image is proprietary and never committed — see
  the README hash table). When it runs, `test_factory_agrees_with_ours` is the
  payoff: a direct factory-vs-ours equivalence check on the narrow logic.

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
| `com_flat` | `reference/com_flat.bin` (05-series) | `0x0801ece8` → `sub_0801eb4c` | `0x2000a718` (+1 min, +2 hr) | `0x20009854+0x64` | bit 24 of `0x2000a758` | via `tools/emu_acfirst.py` |
| `ceaa07` | ceaa-07xx (07-series) | `sub_080352d0` | `0x2000d850` | `0x2000c85c+0x64` | bit 24 of `0x2000d890` | **✔ green on `ceaa-07xx_vE_260214`** |

## Does the AC-First evaluator test any other windows? No.

Proven by tracing which config bytes `sub_080352d0` reads during an isolated
call (`reference/com_flat.bin` = ceaa-07xx): it reads RTC `+1`/`+2` (minute,
hour) and **exactly the three AC-First window pairs** —
config `+0x64/+0x66`, `+0x68/+0x6a`, `+0x6c/+0x6e` (= HR 152-157) — **and no
other config offset**. So it evaluates all **three** AC-First windows (the suite
exercises each slot) but nothing else.

## Extending the pattern to the other time windows

The other RTC-vs-window features each have their **own** evaluator (not a shared
one). Confirmed statically for AC-charge: **`sub_0801d8dc` reads the RTC and the
AC-charge windows** at config `+0x3a..+0x44` (= HR 68-73, per
[`docs/23`](23-arm-config-writer.md)); charge-priority / forced-discharge
(HR 74-89) and OptimalChg (HR 126-131) will have theirs.

To add one:

1. Find its evaluator (`tools/ramxref.py <config-offset> load` on the window's
   config byte names the readers; cross-check it also reads the RTC).
2. Resolve its **isolated-call setup** and **result location** — this is the real
   work. The AC-First evaluator happens to be self-contained (computes its own
   base pointers), so a cold `Emu.call()` just works. **`sub_0801d8dc` does not**:
   a context-free call faults (branches to `pc=0`), so it needs some initialized
   state (a function-pointer/table) seeded first. Find the result flag by diffing
   RAM in-window vs out (the method in `tools/emu_acfirst.py`).
3. Add a `FactoryBackend` profile for it and its vectors. Our
   `acfirst_window_active()` is a **generic** start-incl/end-excl/wrap predicate,
   so it is the oracle for every one of these window types — reuse it (or add a
   thin wrapper) rather than writing new window logic.

The test body never changes; only the backend profile + vectors grow.

See also: [`docs/25`](25-modbus-register-spaces.md) (the AC-First observable and
the IR 126 funnel), [`docs/19`](19-gpio-test-harness.md) (the full-sim harness
this complements).
