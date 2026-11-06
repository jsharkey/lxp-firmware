# Block 7 — config group (`0xABFx`/`0xACxx`)

> **ARM→DSP** config block, id `7`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x080`.
> Payload from `0x15`, all BE16, contiguous stride 2. See the [index](README.md).

| off | → DSP target | | off | → DSP target |
|---|---|---|---|---|
| `0x15` | `0xABFF` | | `0x21` | `0xAC03` |
| `0x17` | `0xAC00` | | `0x23` | `0xAC04` |
| `0x19` | `0xAC01` | | `0x25` | `0xABF4` |
| `0x1B` | `0xAC02` | | `0x27` | `0xABF6` |
| `0x1D` | `0xABF8` | | `0x29` | `0xABFD` |
| `0x1F` | `0xABFA` | | `0x2B` | `0xABFE` |

**Semantics:** targets located, not yet named. Source map:
[`docs/10`](../10-dsp-config-field-map.md).
