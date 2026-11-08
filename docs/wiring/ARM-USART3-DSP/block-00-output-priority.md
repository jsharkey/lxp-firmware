# Block 0 — output priority / AC-First + grid-charge core

> **ARM→DSP** config block, id `0`, `SOF 0x41`. Sets DSP completeness bit
> `DAT_0000b300 |= 0x001`. Payload begins at frame offset `0x15`; all multi-byte
> fields big-endian. See the [index](fields.md) and [`frame-header`](frame-header.md).

This is the most important block: it carries the **output-priority selector** —
including the **"AC First"** value — plus the grid-charge enable/slot core the DSP's
AC-First logic gates on ([`docs/07`](../../07-dsp-ac-first-mode.md)).

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
schedule is stored but inert. See [`docs/07`](../../07-dsp-ac-first-mode.md) for the
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
`HR 145 → (write) 0x2000a343 → this block's 0x1E → DSP 0xADA8`. This chain is now
**proven end-to-end** — the `{0 Bat, 1 PV, 2 AC-First}` enum matches exactly at both
ends and HR 145 is dongle-writable on the factory image
([`hr-controlled-fields.md`](hr-controlled-fields.md) §1). Most of this block's
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
  firmest finding in [`docs/07`](../../07-dsp-ac-first-mode.md); `0xAD84` bit 3 =
  AC-charge enable is the paired gate. The unnamed scalar fields (`0xAD80/81/83/85/86`)
  are located but not individually named.

## Live-decoded HR → byte map (T25) and what our firmware emits

The [HR→push matrix](hr-push-matrix.md) exercised each writable register live
(single-write, fresh boots) and pinned the ARM-side holding-register source of every
HR-driven byte in this block. Several are **packed** (one frame byte combines bits
from more than one register, over a constant base), which the DSP-side table above
shows as the low byte of a BE16 word:

| frame | DSP word | source → transform |
|---|---|---|
| `0x19` | `0xAD83` hi | **HR 120** `SYS_ENABLE` `& 0xFE` (bit0 cleared) |
| `0x1a` | `0xAD83` lo | **HR 90** EPS-volt enum `{208→0, 277→1, 230→2, 240→3}` \| **HR 91** (`== 60 ? 0x08`) \| **HR 146** `LINE_MODE` (`== 1 UPS ? 0x20`) |
| `0x1c` | `0xAD84` lo | `0x02` base\* \| **HR 110** `FUNCTION_EN1` remap `{b0→0x80, b7→0x10, b10→0x20}` \| **HR 112** `SET_SYSTEM_TYPE` `b0→0x08` (= AC-charge enable) |
| `0x1e` | `0xADA8` | **HR 145** `OUTPUT_PRIO_CFG` (static; HR 145 stores only its default live) |
| `0x21` | — | **HR 100** `CUT_VOLT_DISCHG` (BE16, 0.1 V) — T25 1-value resolution; the old "constant" `0x01a4` |
| `0x28` | `0xAD8D` | **HR 20** `PV_INPUT_MODEL` (direct) |
| `0x2c` | `0xAD85` lo | **HR 21** `FUNC_EN` remap `{b1→0x10, b4→0x08, b6→0x04, b10→0x20, b11→0x40}` |

`0x08` in the `0x1c` byte is the DSP's **AC-charge-enable** gate bit (the one AC
First is ANDed with, above) — reached from `SET_SYSTEM_TYPE` bit0. The bit `0x08` on
`0x19`'s word (`0xAD83`) is the EPS **60 Hz** flag.

\* **`0x1c`'s `0x02` bit is a "FuncEn-not-yet-configured" latch** — set at boot and
cleared the first time **HR 21 (`FUNC_EN`) is written, to any value (even 0)**; HR 20
and the others do not affect it. The single-write matrix couldn't see this (it moves
one register from a clean boot); only the absolute cross-image check surfaced it, and
pinning it down showed HR 21 is the sole trigger. Our firmware always has a live,
configured FuncEn, so it is in the cleared state from boot and **omits `0x02`** — which
makes `0x1c` **byte-exact ours==factory in the configured state** (the operating
state, and the one the ABS check exercises, since it writes HR 21). The clean bits
are `0x80`/`0x10`/`0x20` from `FUNCTION_EN1` and `0x08` (AC-charge-enable) from
`SET_SYSTEM_TYPE`.

**Our firmware** emits these bytes in `src/dsp/dsp_config.c` `dsp_build_block0()`.
Routing (which register moves which byte) is verified ours==factory by
[`test_dsp_push.py`](../../../tests/test_dsp_push.py)
`test_{factory,ours}_grid_push_matches_spec`; all six HR-driven bytes are
additionally verified **byte-exact ours==factory** by the absolute cross-image check
`test_ours_matches_factory_absolute` (`0x1c` in the configured state); the transforms
are locked by the host test [`test_dsp_config.c`](../../../tests/test_dsp_config.c). The surrounding
identity/version template (`0x15–0x18`, `0x1b`, `0x1d`, `0x1f–0x27`, `0x29–0x2e`) is
**not** driven by any holding register. Decoded (T10): it is boot-**computed** into
the settings working struct `0x2000c8xx` (zero pre-boot, written during boot — not a
flash const table; an apparent `0x0802exxx` flash source was a CRC-table false
match), and its values are recognisable **default settings / model constants** —
e.g. `0x29:2a = 0x2ee0` = 12000 = **12 kW rated power** (model-specific), `0x1f:20 =
0x01b8` = 440 and `0x21:22 = 0x01a4` = 420 (voltage limits). So block 0 is byte-exact
for its HR-driven bytes; the template is a **settings-defaults** matter (ours adopting
the same defaults, T03), not a push-mechanism gap. See
[block-03_06 §Constant-template bytes](block-03_06-gridcharge-slots.md).
