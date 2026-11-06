# Block 8 — two more calibration gains + two reserved (`0xABDx`/`0xABEx`)

> **ARM→DSP** config block, id `8`, `SOF 0x41`. Sets `DAT_0000b300 |= 0x100`.
> Payload from `0x15`, all BE16. Shortest block (4 fields). See the [index](README.md).

## What this block is — inferred (**medium-high confidence**)

The first two fields continue the **measurement calibration-gain** table of
[`block-02`](block-02.md)/[`block-07`](block-07.md): `0xABDC` and `0xABDD` are both
hard-defaulted to **`0x400` = 1024 (unity)** by `FUN_0009C44E`, the hallmark of a
Q10 calibration coefficient. The last two (`0xABE4`/`0xABE5`) are **stored by the
deserialiser but never read** anywhere in the 12kXP image — reserved / inert here.

| off | → DSP target | ARM src | role | confidence |
|---|---|---|---|---|
| `0x15` | `0xABDC` | ext-settings `0x2000990A` | calibration gain (unity-default) | **med-high** |
| `0x17` | `0xABDD` | ext-settings `0x2000990C` | calibration gain (unity-default) | **med-high** |
| `0x19` | `0xABE4` | **status** `0x2000A936` | received, **not consumed in this image** (reserved) | **med** |
| `0x1B` | `0xABE5` | ext-settings `0x20009910` | received, **not consumed in this image** (reserved) | **med** |

Note `0xABE4`'s ARM source is a **status** word (`0x2000A936`), not an ext-setting
— so even if a variant consumed it, it would be a live value rather than a trim.
Because neither `0xABE4` nor `0xABE5` is read by the DSP here, their purpose can't
be pinned from this image; a build that activates more measurement channels (or the
18kPV image) may consume them.

Source map: [`docs/10`](../10-dsp-config-field-map.md); ARM provenance:
[`field-provenance`](field-provenance.md). Mechanism + evidence:
[`block-02`](block-02.md).
