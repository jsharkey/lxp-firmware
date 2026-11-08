# IR 77 — ACInputType

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | range | note |
|---|---|---|---|
| IR 77 | ACInputType | 0 or 1 | 0 = Grid, 1 = Generator (12K hybrid) |

## Where the data comes from

Reports the AC-input status (the spec labels it grid vs generator). **Empirically
(T27):** on `ceaa-07xx` the factory serves IR 77 = **`0x20`** (bit 5) in the bare-boot
state, and it is **unchanged by HR 146 LineMode** (writing LineMode 0/1/2 leaves IR 77
at `0x20`) — so it is **not** a LineMode derivation (the earlier candidate is ruled
out). IR 77 is a **factory-populated status/flags value** (more than the spec's plain
`0/1`): it is one of the T23 "ours-unpopulated IR" set (IR 77, 80, 83, 88, 89, 113,
125, 126 — telemetry the factory fills and ours does not yet). **Open (narrowed
hand-off):** the exact getter word behind IR 77 and the grid/generator detection that
sets/clears its bits need the AC-input-detection path seeded (not reachable by the
bare harness); `0x20` is the no-input default.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** IR 77 is read on both images in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) /
  [`regsweep_expected.py`](../../../tests/regsweep_expected.py) and tracked as a
  **known-diff: ours-unpopulated IR** (factory `0x20`, ours `0` — not yet served). A
  focused oracle awaits the detection source being pinned (above).
