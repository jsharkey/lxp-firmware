# Blocks 3–6 — grid-charge "slot" parameters

> **ARM→DSP** config blocks, ids `3`–`6`, `SOF 0x41`. Set `DAT_0000b300`
> `0x008`/`0x010`/`0x020`/`0x040` (block 3 also `|= 0x200` if its trailing value
> validates). Payload from `0x15`, big-endian. See the [index](README.md).

These four blocks share a shape: a 2-byte **slot-enable mask → `0xAD54`** at `0x15`,
then runs of **6-byte groups**, each passed to one of the DSP's grid-charge slot
change-detect/commit functions (they store into the `0xAD8F…`/`0xAD9C…`/`0xADAC…`
slot records and, **in AC First**, enqueue changes via `FUN_0009C756`, docs/07). A
few direct scalars are interleaved. These correspond to the ARM-side schedule
**time-windows** (dongle holding regs 64–89 / the parallel AC-First windows).

> **ARM-source provenance (`0x17…0x21` of blocks 4 and 5):** traced end-to-end from
> the builder in `com_flat.bin` — see [`field-provenance`](field-provenance.md). The
> ARM writes **six sequential u16 window values** here (three `start/end` pairs), via
> the slot-committer family → slot records → the block filler. **Block 4 `0x17…0x21`
> = AC-charge windows HR 68–73**; **block 5 `0x17…0x21` = AC-First windows HR 152–157**
> ([dongle doc](../modbus-dongle/holding-064_089-charge-discharge-schedule.md)). This
> **refines the old "triplet `[val_a, rsv, val_b]`" reading below**: `0x19`/`0x1F`
> are **not reserved** — they carry the window-*end* values. The pairs are
> `(0x17,0x19)`,`(0x1B,0x1D)`,`(0x1F,0x21)`. The DSP-side handler grouping (the
> `FUN_0009Cxxx` column) should be re-derived against this; the per-window *active
> verdict* stays ARM-side (docs/07), only the times are pushed. The schedule
> **power/SOC** (HR 66/67) and the **charge-priority / forced-discharge** features
> (HR 74–89) are **not** in the canonical settings struct and their push status is
> unresolved (field-provenance "what is NOT resolved").

### Block 3 (`b300 |= 0x008`, and `|= 0x200` if the trailing value validates)

| off | w | → |
|---|---|---|
| `0x15` | 2 | `0xAD54` (mask) |
| `0x17`/`0x19`/`0x1B` | 2·3 | →`FUN_0009C0C4` (`0x19` rsv) |
| `0x1D`/`0x1F`/`0x21` | 2·3 | →`FUN_0009C118` (`0x1F` rsv) |
| `0x23`/`0x25`/`0x26` | 2+1+1 | →`FUN_0009CC77` (`0x25` rsv byte; `0x26` u8 arg) |
| `0x27` | 1 | flag: if `==1`, clears `0xB254/0xB255/0xAE2D` |
| `0x28` | 2 | `0xADA3` |
| `0x2A` | 2 | `0xAD87` (stored only if `FUN_0009DA5A` validates; sets `b300 |= 0x200`) |

### Block 4 (`b300 |= 0x010`) — carries the **AC-charge** windows

| off | w | ARM source | → |
|---|---|---|---|
| `0x15` | 2 | slot mask `0x2000a7a8` | `0xAD54` (mask) |
| `0x17` | 2 | slot `a370` ← **HR 68** (w0 start) | →`FUN_0009CCBD` |
| `0x19` | 2 | slot `a372` ← **HR 69** (w0 end) | *(was "rsv" — actually w0 end)* |
| `0x1B` | 2 | slot `a374` ← **HR 70** (w1 start) | →`FUN_0009CD03`? (regroup) |
| `0x1D` | 2 | slot `a376` ← **HR 71** (w1 end) | |
| `0x1F` | 2 | slot `a378` ← **HR 72** (w2 start) | *(was "rsv" — actually w2 start)* |
| `0x21` | 2 | slot `a37a` ← **HR 73** (w2 end) | |
| `0x23` | 2 | — | `0xAD8C` |
| `0x25` | 2 | — | `0xAD55` |
| `0x27`/`0x29`/`0x2B` | 2·3 | slot `a36a`/`a36c`/… | →`FUN_0009C309` (`0x29` rsv) |

### Block 5 (`b300 |= 0x020`) — carries the **AC-First** windows

| off | w | ARM source | → |
|---|---|---|---|
| `0x15` | 2 | slot mask `0x2000a7a8` | `0xAD54` (mask) |
| `0x17` | 2 | slot `a37c` ← **HR 152** (w0 start) | →`FUN_0009CD49` |
| `0x19` | 2 | slot `a37e` ← **HR 153** (w0 end) | *(was "rsv" — actually w0 end)* |
| `0x1B` | 2 | slot `a380` ← **HR 154** (w1 start) | →`FUN_0009C7EE`? (regroup) |
| `0x1D` | 2 | slot `a382` ← **HR 155** (w1 end) | |
| `0x1F` | 2 | slot `a384` ← **HR 156** (w2 start) | *(was "rsv" — actually w2 start)* |
| `0x21` | 2 | slot `a386` ← **HR 157** (w2 end) | |
| `0x23`/`0x25`/`0x27` | 2·3 | slot records | →`FUN_0009C01C` (`0x25` rsv) |
| `0x29` | 2 | — | →`FUN_0009BC08(2, …)` — **AC-First command**, only if `b300 & 1` (block 0 already received) |

### Block 6 (`b300 |= 0x040`)

| off | w | → |
|---|---|---|
| `0x15` | 2 | `0xAD54` (mask) |
| `0x17`/`0x19`/`0x1B` | 2·3 | →`FUN_0009CBEB` (`0x19` rsv) |
| `0x1D`/`0x1F`/`0x21` | 2·3 | →`FUN_0009BFC8` (`0x1F` rsv) |
| `0x23`/`0x25`/`0x27` | 2·3 | →`FUN_0009CC31` (`0x25` rsv) |

**Triplet convention (superseded for `0x17…0x21`):** docs/10 read these runs as
6-byte triplets `[val_a, rsv, val_b]` → `handler(val_b, val_a)`. The ARM-source trace
above shows that is wrong for the window runs in blocks 4/5: the ARM fills **six
consecutive window u16s** (`start,end` ×3), so the middle word is a real value, not a
zero. The DSP handler column (`FUN_0009Cxxx`) is kept as-is pending a re-derivation of
how the DSP *groups* these on its side; the `docs/10` byte offsets/widths/targets are
unchanged, only the "reserved" interpretation is corrected. On-DSP storage/semantics:
[`docs/07`](../07-dsp-ac-first-mode.md). ARM source map:
[`field-provenance`](field-provenance.md).
