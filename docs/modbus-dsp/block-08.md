# Block 8 — config group (`0xABDx`/`0xABEx`)

> **ARM→DSP** config block, id `8`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x100`.
> Payload from `0x15`, all BE16. See the [index](README.md).

| off | → DSP target |
|---|---|
| `0x15` | `0xABDC` |
| `0x17` | `0xABDD` |
| `0x19` | `0xABE4` |
| `0x1B` | `0xABE5` |

Shortest block (4 fields). **Semantics:** targets located, not yet named. Source
map: [`docs/10`](../10-dsp-config-field-map.md).
