# Block 2 — config group (`0xABxx`)

> **ARM→DSP** config block, id `2`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x004`.
> Payload from `0x15`, all BE16. See the [index](README.md).

Note the `+4` after the first field (a 2-byte reserved gap at `0x17`).

| off | → DSP target | | off | → DSP target |
|---|---|---|---|---|
| `0x15` | `0xABDB` | | `0x23` | `0xABE2` |
| `0x17` | rsv | | `0x25` | `0xABF3` |
| `0x19` | `0xABDF` | | `0x27` | `0xABF5` |
| `0x1B` | `0xABE0` | | `0x29` | `0xABE3` |
| `0x1D` | `0xABF7` | | `0x2B` | `0xABFB` |
| `0x1F` | `0xABF9` | | `0x2D` | `0xABFC` |
| `0x21` | `0xABE1` | | | |

**Semantics:** targets located, not yet named. Source map:
[`docs/10`](../10-dsp-config-field-map.md).
