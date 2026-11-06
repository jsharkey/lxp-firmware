# Block 1 — config group (`0xB23x`)

> **ARM→DSP** config block, id `1`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x002`.
> Payload from `0x15`, big-endian. See the [index](README.md).

| off | w | rd | → DSP target | note |
|---|---|---|---|---|
| `0x15` | 1 | u8 | `0xB235` | read as a byte at `0x15` **before** the block's internal pointer resets to `0x16` (reuses the slot block 0 reads at `0x15`) |
| `0x16` | 2 | BE16 | `0xB236` | |
| `0x18` | 2 | BE16 | `0xB237` | |
| `0x1A` | 2 | BE16 | `0xB238` | |
| `0x1C` | 2 | BE16 | `0xB239` | |
| `0x1E` | 2 | BE16 | `0xB23A` | |
| `0x20` | 2 | BE16 | `0xB234` | |
| `0x22` | 6 | — | rsv | `+8` gap — emit (0) |
| `0x28` | 2 | BE16 | `0xB23B` | |

**Semantics:** targets located (the `0xB234–0xB23B` cluster) but **not yet named**
as product settings — the open leg is matching each to the dongle holding register
that feeds it. Source map: [`docs/10`](../10-dsp-config-field-map.md).
