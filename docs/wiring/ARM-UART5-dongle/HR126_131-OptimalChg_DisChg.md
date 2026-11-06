# HR 126-131 — OptimalChg_DisChg (48-slot time table)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

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

**A configuration time-table, stored in ARM RAM.** It is the classic register
that makes the **"126 trap"** concrete: **HR 126-131 is this config table**,
while **IR 126 is an unrelated status word** (generator energy / AC-First active
bit) — different space, different meaning ([`docs/25`](../../25-modbus-register-spaces.md)).

Writing it over the dongle stores the six words at a dedicated RAM block
(`0x2000D814`, next to the RTC calendar), and a `0x03` read serves them back from
there — `0x06`/`0x10` writes and `0x03` reads round-trip cleanly.

### Dormant in ceaa-07xx (proven)

Despite the spec describing a half-hour charge/discharge schedule, this factory
image **never evaluates the table against the clock.** The feature is nominally
gated by **`stSysEnable.HalfHourACChrStartEn` (HR 120 bit 0)**, but even with that
enabled the table is not consumed:

- **Static:** the only code that references the `0x2000D814` block is the config
  clear/init (`sub_080147ac`), the Modbus holding **getter** (`sub_0801d48c`, the
  `0x03` read path) and **setter** (`sub_0801f596`, the `0x06`/`0x10` write path).
  No function computes a slot index from the RTC and reads a mark.
- **Dynamic:** a `UC_HOOK_MEM_READ` over `0x2000D814-0x2000D81F` across a long
  run sees **zero** reads during normal operation; the hook fires only when a
  dongle `0x03` of HR 126-131 runs the getter (6 reads, from `sub_0801d48c`).
- **Not pushed to the DSP:** writing the table (all-zero vs all-charge) moves
  **no** byte of any of the 9 DSP config-push blocks; and the DSP never evaluates
  time windows anyway ([`docs/wiring/ARM-USART3-DSP/clock.md`](../../wiring/ARM-USART3-DSP/clock.md)).

So there is **no RTC-evaluated verdict and no DSP push** for this table on this
image — the one black-box observable is the **store/read-back round-trip**. Our
firmware therefore keeps a tested *pure* evaluator (`optchg_slot_mode()`) but
deliberately does **not** wire it into the loop, matching the factory's dormancy.
(See [`docs/31` Q5](../../31-factory-quirks.md).)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Slot lookup (HR 126-131 → current half-hour mark):** host unit test
  [`test_optchg.c`](../../../tests/test_optchg.c) against the pure evaluator
  `optchg_slot_mode()` ([`include/inv/optchg.h`](../../../include/inv/optchg.h),
  [`src/sched/optchg.c`](../../../src/sched/optchg.c)) — slot indexing, the
  8-slots-per-register / 2-bits-per-slot LSB-first packing, all three marks, the
  register boundaries, the midnight edges, and reads past the end of the table.
  Toolchain-free and deterministic, the same tier as `test_acfirst.c`.

- **Store/read-back over the dongle (HR 126-131):** common black-box test
  [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_modbus_optchg_table_roundtrip`
  writes a distinct 2-bit pattern into each of the six table registers and reads
  all six back — the same code against both images (factory + ours). This is the
  **only** black-box observable the table has on ceaa-07xx (see the dormancy
  finding above): there is no RTC-evaluated verdict and no DSP push to assert, so
  no `optchg` profile is added to [`timewindow_contract.py`](../../../tests/timewindow_contract.py).
  If a later image is found to evaluate the table, that is where its oracle goes.
