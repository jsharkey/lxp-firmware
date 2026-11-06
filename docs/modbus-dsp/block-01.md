# Block 1 — battery charge/discharge **limit set** (`0xB23x`)

> **ARM→DSP** config block, id `1`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x002`.
> Payload from `0x15`, big-endian. See the [index](README.md).

## What this block is — inferred (**medium-high confidence**)

Block 1 is the **battery charge/discharge limit set** the DSP's power loop clamps
against. Evidence:

- **ARM source is the battery-limits working struct.** The builder reads this whole
  block from `0x2000a68c…0x2000a69f`, the region
  [field-provenance](field-provenance.md) classifies as "battery charge/discharge
  **limits**, computed from BMS + settings."
- **DSP consumer is the limit calculator `FUN_0009520C`.** It picks between the
  **ARM-pushed set (`0xB234–B23B`)** and a **live BMS set (`0xB22C–B233`)** — using
  the pushed values when grid-charge is off or the BMS link is quiet — then derives
  the working charge-voltage target `0xB222`/`0xB243` and the charge/discharge
  **current** limits `0xB245…0xB24B`, with clamps that read as battery engineering
  units (e.g. charge-V floor `0x1E0` = 48.0 V, `0xB243` clamped `0x12C0…6000` =
  48.00–60.00 V; currents min'd against `0xADA4/5/7`).
- **The BMS handler `FUN_00093694`** (a CAN/BMS record parser) fills the live set
  `0xB22C–B233` and, when echoing/looking up, pairs each live value with its pushed
  counterpart from `0xB234–B23B` — i.e. the pushed block is the *configured* limit,
  the `0xB22C` set is the *live* one.

So the ARM pushes the configured battery limits; the DSP continuously takes the
**min** of configured vs live-BMS and clamps the converter to it.

> **HR cross-check (both images).** The DSP reads block-1 voltages in **0.1 V**
> and currents in **0.1 A**; the candidate dongle registers are documented in
> exactly those units — HR 99/144/148 (charge/float/nominal voltage, 0.1 V) and
> HR 101/102 (charge/discharge current, A → 0.1 A). The units agree end to end, so
> the **block identity is high**; because block 1 is *computed* from BMS+settings
> (field-provenance), no single HR maps 1:1 to a `0xB23x` field — control is
> **indirect**. Full chain + factory-image writability:
> [`hr-controlled-fields.md`](hr-controlled-fields.md) §3.

## Fields — per-field guess (**confidence per row**)

Offsets/targets from [`docs/10`](../10-dsp-config-field-map.md); roles from
`FUN_0009520C` (which copies `0xB234→0xB224 … 0xB23B→0xB22B` and uses each in the
charge/discharge math). Physical unit guesses are **low-medium** pending a
BMS-register cross-check.

| off | w | → DSP target | role (guess) | confidence |
|---|---|---|---|---|
| `0x15` | 1 | `0xB235` | SOC-related limit (tested `>99`), → `0xB225` | **low** |
| `0x16` | 2 | `0xB236` | **flags / enable word** (bit `0x100` = limits valid/enable; bit `0x1`) | **med-high** |
| `0x18` | 2 | `0xB237` | **max charge voltage** (0.1 V; ceiling for the charge-V target, floor 48.0 V) | **medium** |
| `0x1A` | 2 | `0xB238` | charge-voltage companion / hysteresis (paired with `0xB237`) | **low** |
| `0x1C` | 2 | `0xB239` | **charge current limit** (0.1 A; min'd into the charge-current output) | **medium** |
| `0x1E` | 2 | `0xB23A` | **discharge current limit** (0.1 A; min'd into the discharge-current output) | **medium** |
| `0x20` | 2 | `0xB234` | charge-limit companion (→ `0xB224`; paired with `0xB235`) | **low** |
| `0x22` | 6 | rsv | `+8` source gap — ARM writes `0x20` as 8 B; DSP keeps only the first word | **proven** |
| `0x28` | 2 | `0xB23B` | discharge-limit companion (→ `0xB22B`; likely discharge cutoff voltage) | **low** |

> The flags word `0xB236` is the most-read field (also written by `FUN_0009E433`),
> gating whether the pushed limits are honoured — hence **med-high** on it while the
> individual numeric limits stay **medium/low** until matched to BMS registers.

Source map: [`docs/10`](../10-dsp-config-field-map.md); ARM provenance:
[`field-provenance`](field-provenance.md) (block 1 = battery-limits struct).
