# HR 126-131 — OptimalChg_DisChg (48-slot time table)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

A **48-slot × 2-bit** table packed across 6 registers: each half-hour of the day
(`00:00-00:30`, …, `23:30-00:00`) carries a mark **0 no action, 1 charging,
2 discharging** (default 0). The marks pack **8 per register, 2 bits each,
least-significant first** — `Time0` in bits 0-1, `Time1` in bits 2-3, … `Time7`
in bits 14-15 (per the EG4 18kPV-12LV Modbus protocol). Slot *k* covers minutes
`[30·k, 30·k+30)`.

| reg | slots | time span |
|---|---|---|
| HR 126 | Time0-7 | 00:00-04:00 |
| HR 127 | Time8-15 | 04:00-08:00 |
| HR 128 | Time16-23 | 08:00-12:00 |
| HR 129 | Time24-31 | 12:00-16:00 |
| HR 130 | Time32-39 | 16:00-20:00 |
| HR 131 | Time40-47 | 20:00-00:00 |

## Side-effects of writing

**A configuration time-table, persisted to config flash and evaluated ARM-side**
against the clock. This is the classic register that makes the **"126 trap"**
concrete: **HR 126-131 is this config table**, while **IR 126 is an unrelated
status word** (generator energy / AC-First active bit) — different space, different
meaning ([`docs/25`](../25-modbus-register-spaces.md)). The ARM compares the
current half-hour slot against the RTC it owns; like the other time windows it is
not pushed to the DSP as a per-slot verdict.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **Slot lookup (HR 126-131 → current half-hour mark):** host unit test
  [`test_optchg.c`](../../tests/test_optchg.c) against the pure evaluator
  `optchg_slot_mode()` ([`include/inv/optchg.h`](../../include/inv/optchg.h),
  [`src/sched/optchg.c`](../../src/sched/optchg.c)) — slot indexing, the
  8-slots-per-register / 2-bits-per-slot LSB-first packing, all three marks, the
  register boundaries, the midnight edges, and reads past the end of the table.
  Toolchain-free and deterministic, the same tier as `test_acfirst.c`.

The factory ARM evaluator for this table has not been located yet, and the spec
notes no externally observable per-slot verdict (it is consumed internally, not
pushed to the DSP or mirrored to an input register), so there is no
factory-vs-ours Unicorn contract for it the way AC-First has one. If that
evaluator and an observable are found, add an `optchg` profile to
[`timewindow_contract.py`](../../tests/timewindow_contract.py).
