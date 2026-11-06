# Block 2 — measurement **calibration-gain** table (`0xABxx`)

> **ARM→DSP** config block, id `2`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x004`.
> Payload from `0x15`, all BE16. See the [index](fields.md).
>
> Note the `+4` after the first field (a 2-byte reserved gap at `0x17`).

## What this block is — inferred (**high confidence**)

Block 2 carries **per-channel analog-measurement calibration gains** (factory trims),
not product settings. Three independent lines of evidence agree:

1. **Default = unity in Q10.** `FUN_0009C44E` (the init/reset path, called from
   `FUN_0009A787`) hard-sets every one of these targets — and the block-7/8 ones —
   to **`0x400` = 1024**. The consumers divide by `>> 10` (÷1024), so `0x400`
   is a **gain of 1.000**. A whole cluster defaulting to "1.0" is a calibration
   table, not a settings group.
2. **Used as a multiplicative gain on a raw measurement.** The periodic
   acquire-and-scale routine `FUN_0009BF20` calls a family of helpers
   (`FUN_00098D1D`, `FUN_0009AE3F`, `FUN_0009B8C2`, `FUN_0009C919`) that each do:
   ```c
   calibrated = (coeff * FUN_0009C9AB(module, raw_channel)) >> 10;   // raw × gain/1024
   if (calibrated < 100) calibrated = 0;   // small-signal deadband (most channels)
   ```
   `FUN_0009C9AB` is the raw-sample processor (range-scaled Newton/averaging — an
   RMS/√ filter); the block-2 word is the gain wrapped around it. Output lands in
   the **calibrated-measurement bank `0xAB5x–0xAB6x`**.
3. **Validated, and forced back to unity if bad.** `FUN_00097B46` runs each coeff
   through a range check (`FUN_0009E742`/`FUN_0009E74F`) and, on failure, resets it
   to `0x400`. Firmware only range-guards-to-unity a *calibration* coefficient.

This also explains the ARM-side provenance ([field-provenance](field-provenance.md)):
blocks 2/7/8 come from the **ext-settings area `0x20009908…0x20009944`, default-inited
to `0x400`, and not served by the holding getter `fn_ceaa`** — i.e. no Modbus
*read* register exposes them, exactly as expected for factory calibration.

## Fields — each a gain for one measurement channel (**confidence per row**)

The gain → raw-source → calibrated-output mapping, read from the consumers above.
"Role" is the *kind* of value (a measurement gain); which physical quantity
(voltage / current / temperature) each raw channel `0xA8xx` is has **not** been
mapped yet, so the physical name is a **low-confidence guess**.

| off | → DSP target | raw src | calibrated out | consumer | confidence |
|---|---|---|---|---|---|
| `0x15` | `0xABDB` | — | *(validator only)* | `FUN_00097B46` | gain — **high**; channel — unknown |
| `0x17` | rsv | | | | — |
| `0x19` | `0xABDF` | `0xA8A2` | `0xAB50` | `FUN_0009B8C2` | gain — **high**; ch on module `0xA8A5` |
| `0x1B` | `0xABE0` | `0xA884` | `0xAB55` | `FUN_0009AE3F` | gain — **high** |
| `0x1D` | `0xABF7` | — | *(default/validate only in this image)* | — | gain-slot — **med** |
| `0x1F` | `0xABF9` | — | *(default/validate only in this image)* | — | gain-slot — **med** |
| `0x21` | `0xABE1` | — | *(default/validate only in this image)* | — | gain-slot — **med** |
| `0x23` | `0xABE2` | `0xA8AA` | `0xAB51` | `FUN_0009C919` | gain — **high**; ch on module `0xA8AD` |
| `0x25` | `0xABF3` | `0xA80E` | `0xAB53`,`0xAB59` | `FUN_00098D1D` | gain — **high** |
| `0x27` | `0xABF5` | `0xA82A` | `0xAB54`,`0xAB5B` | `FUN_00098D1D` | gain — **high** |
| `0x29` | `0xABE3` | `0xA87E` | `0xAB52` | `FUN_0009AE3F` | gain — **high** |
| `0x2B` | `0xABFB` | `0xA88E` | `0xAB5D` | `FUN_0009AE3F` | gain — **high** |
| `0x2D` | `0xABFC` | `0xA898` | `0xAB5E` | `FUN_0009AE3F` | gain — **high** |

> **Why some rows have no consumer.** `0xABF7/F9/E1` are defaulted and validated
> (so they *are* calibration slots) but no read of them appears in the 12kXP image —
> either the channel they trim is inactive in this build or lives on a path not yet
> traced. Marked **med** on the role, not **high**, for honesty.

The module handles (`0xA804` main, `0xA8A5`/`0xA8AD` sub-modules — gated: when the
handle is `0`, `FUN_0009B8C2`/`FUN_0009C919` zero their outputs) suggest the
sub-modules are optional measurement sources (parallel unit / external CT / PV
string) whose channels are only calibrated when present. Identity of each
sub-module is a **low-confidence guess**.

Source map: [`docs/10`](../../10-dsp-config-field-map.md); ARM provenance:
[`field-provenance`](field-provenance.md). Block 7 is the **same table, more
channels** ([`block-07`](block-07.md)); block 8 starts another two
([`block-08`](block-08.md)).
