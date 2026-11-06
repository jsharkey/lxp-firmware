# Block 0 — output priority / AC-First + grid-charge core

> **ARM→DSP** config block, id `0`, `SOF 0x41`. Sets DSP completeness bit
> `DAT_0000b300 |= 0x001`. Payload begins at frame offset `0x15`; all multi-byte
> fields big-endian. See the [index](README.md) and [`frame-header`](frame-header.md).

This is the most important block: it carries the **output-priority selector** —
including the **"AC First"** value — plus the grid-charge enable/slot core the DSP's
AC-First logic gates on ([`docs/07`](../07-dsp-ac-first-mode.md)).

## Fields (frame offset → DSP RAM target)

| off | w | rd | → DSP target | meaning |
|---|---|---|---|---|
| `0x15` | 2 | BE16 | `0xAD81` | — |
| `0x17` | 1 | u8 | *(cond)* | if priority `<2` and `≠0` → high byte of `0xAD80` |
| `0x18` | 1 | u8 | `0xAD80` (low) | — |
| `0x19` | 2 | BE16 | `0xAD83` | change-detected |
| `0x1B` | 2 | BE16 | `0xAD84` | **AC/grid-charge flags**; **bit 3 (`0x08`) = AC-charge enable** — the bit AC-First is ANDed with (docs/07) |
| `0x1D` | 1 | u8 | →`FUN_0009E2A6` | — |
| **`0x1E`** | **1** | **u8** | **`0xADA8`** | **OUTPUT PRIORITY — `0` Battery / `1` PV / `2` AC First** |
| `0x1F` | 2 | BE16 | →`FUN_0009C070` arg2 | grid-charge slot |
| `0x21` | 2 | BE16 | rsv | emit, value unused |
| `0x23` | 2 | BE16 | →`FUN_0009C070` arg1 | grid-charge slot |
| `0x25` | 2 | BE16 | `0xAD54` | per-slot enable mask |
| `0x27` | 1 | u8 | `0xAD96` | — |
| `0x28` | 1 | u8 | `0xAD8D` | — |
| `0x29` | 2 | — | rsv | skipped |
| `0x2B` | 2 | BE16 | `0xAD85` | change-detected |
| `0x2D` | 1 | u8 | `0xAD86` | — |
| `0x2E` | 1 | u8 | `0xADA9` | — |

Payload ends at `0x2F` (CRC/padding follows per the frame length).

## The AC-First selector — the field the user asked about

**Output priority is the single byte at frame offset `0x1E`**, stored to DSP
`g_outputPrio = 0x00ADA8`. Its enum (matching the dongle holding register
`HR_OUTPUT_PRIO` / `include/inv/modbus_map.h`) is:

| value | meaning |
|---|---|
| `0` | Battery first |
| `1` | PV first |
| **`2`** | **AC First** |

So "AC First" is literally **`0xADA8 == 2`** on the DSP. The DSP's real-time FSM
tests `g_outputPrio == 2` to decide "are we in AC First?" — the only `{Bat, PV, AC
First}` enum in the system (`docs/07`).

**It is a gate, not a mode function.** AC First is almost always ANDed with the
AC/grid-charge enable bit in the `0x1B → 0xAD84` flags word:

```
g_outputPrio == 2  &&  (g_acChargeFlags & 0x08) == 0x08     // "AC First AND grid-charge enabled"
```

This idiom appears ~14× in the DSP; each occurrence is further qualified by one bit
of the slot-enable mask `0xAD54` (`0x1E → … → 0x25`). Only when it holds does the
DSP enqueue the AC-charge schedule changes (via `FUN_0009C756`); otherwise the
schedule is stored but inert. See [`docs/07`](../07-dsp-ac-first-mode.md) for the
full gate analysis.

## Flow (dongle → DSP)

```
dongle holding reg (output-priority / AC-charge enable / grid-charge slots)
  → ARM settings struct
  → this block (FUN_08026830: byte @ 0x1E = priority, BE16 @ 0x1B = flags, …)
  → DSP FUN_00092EE2  →  0xADA8 (priority), 0xAD84 (flags), 0xAD54 (slot mask), …
  → DSP AC-First FSM (g_outputPrio==2 && g_acChargeFlags&8)
```

**ARM-side source (docs [field-provenance](field-provenance.md)):** the builder
reads output priority from the *working* location `0x2000a343` (low byte), not
directly from its holding register **HR 145 `OutputPrioConfig`** — i.e.
`HR 145 → (write) 0x2000a343 → this block's 0x1E → DSP 0xADA8`. Most of this block's
other fields come from the grid-charge **slot-record** working struct
(`0x2000a330…`), except `0x28` which is read directly from **HR 20 `PVInputModel`**
(→ `0xAD8D`) and the slot-enable mask `0x25` (`0x2000a7a8` → `0xAD54`).

The window **start/stop times** for AC First are evaluated ARM-side against the RTC
and are **not** in this block — they drive the schedule the ARM pushes elsewhere
(docs/07/08); this block carries the *selector* and *enable*, which is what makes
the DSP act on them.

## Confidence

- **High:** offsets/widths/endianness/targets (cross-validated, block 0 checked
  against the raw listing). `0xADA8` = output priority and `== 2` = AC First is the
  firmest finding in [`docs/07`](../07-dsp-ac-first-mode.md); `0xAD84` bit 3 =
  AC-charge enable is the paired gate. The unnamed scalar fields (`0xAD80/81/83/85/86`)
  are located but not individually named.
