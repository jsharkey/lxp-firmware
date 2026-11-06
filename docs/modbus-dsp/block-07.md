# Block 7 — measurement **calibration-gain** table, continued (`0xABFx`/`0xACxx`)

> **ARM→DSP** config block, id `7`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x080`.
> Payload from `0x15`, all BE16, contiguous stride 2. See the [index](README.md).

## What this block is — inferred (**high confidence**)

Same family as [`block-02`](block-02.md): **per-channel measurement calibration
gains**, Q10 fixed-point, **unity = `0x400` = 1024**. Every target here is among
those `FUN_0009C44E` hard-defaults to `0x400`, is validated-to-unity by
`FUN_00097B46`, and is applied as `calibrated = raw × coeff >> 10` by the periodic
acquire routine `FUN_0009BF20` (via `FUN_00098D1D`/`FUN_0009B8C2`/`FUN_0009C919`).
See block-02 for the full mechanism and evidence. ARM-side these come from the same
ext-settings area, invisible to any Modbus read register
([field-provenance](field-provenance.md)).

## Fields — gain → channel (**confidence per row**)

| off | → DSP target | raw src | calibrated out | consumer | confidence |
|---|---|---|---|---|---|
| `0x15` | `0xABFF` | `0xA8B2` | `0xAB5F` | `FUN_0009B8C2` | gain — **high** (module `0xA8A5`) |
| `0x17` | `0xAC00` | `0xA8B8` | `0xAB60` | `FUN_0009B8C2` | gain — **high** (module `0xA8A5`) |
| `0x19` | `0xAC01` | `0xA8BE` | `0xAB61` | `FUN_0009C919` | gain — **high** (module `0xA8AD`) |
| `0x1B` | `0xAC02` | `0xA8C4` | `0xAB62` | `FUN_0009C919` | gain — **high** (module `0xA8AD`) |
| `0x1D` | `0xABF8` | — | *(default/validate only in this image)* | — | gain-slot — **med** |
| `0x1F` | `0xABFA` | — | *(default/validate only in this image)* | — | gain-slot — **med** |
| `0x21` | `0xAC03` | `0xA846` | `0xAB63` | `FUN_00098D1D` | gain — **high** |
| `0x23` | `0xAC04` | `0xA850` | `0xAB64` | `FUN_00098D1D` | gain — **high** |
| `0x25` | `0xABF4` | `0xA81C` | `0xAB5A` | `FUN_00098D1D` | gain — **high** |
| `0x27` | `0xABF6` | `0xA838` | `0xAB5C` | `FUN_00098D1D` | gain — **high** |
| `0x29` | `0xABFD` | `0xA8CA` | `0xAB57` | `FUN_0009AE3F` | gain — **high** |
| `0x2B` | `0xABFE` | `0xA8D0` | `0xAB58` | `FUN_0009AE3F` | gain — **high** |

Which physical quantity each raw channel `0xA8xx` carries (voltage / current /
temperature) is **not** yet mapped — the *role* (a measurement gain) is high
confidence; the physical name would be a **low-confidence guess**. Mapping the
`0xA8xx` raw-measurement array to physical channels is the natural next step and
would name every gain in blocks 2 & 7 at once.

Source map: [`docs/10`](../10-dsp-config-field-map.md); ARM provenance:
[`field-provenance`](field-provenance.md). Mechanism + evidence:
[`block-02`](block-02.md).
