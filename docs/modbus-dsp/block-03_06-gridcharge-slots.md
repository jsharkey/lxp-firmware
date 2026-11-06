# Blocks 3–6 — grid-charge "slot" parameters

> **ARM→DSP** config blocks, ids `3`–`6`, `SOF 0x41`. Set `DAT_0000b300`
> `0x008`/`0x010`/`0x020`/`0x040` (block 3 also `|= 0x200` if its trailing value
> validates). Payload from `0x15`, big-endian. See the [index](README.md).

These four blocks share a shape: a 2-byte **slot-enable mask → `0xAD54`** at `0x15`,
then runs of **6-byte triplets** `[val_a (BE16), rsv (BE16), val_b (BE16)]`, each
passed as `handler(val_b, val_a)` to one of the DSP's grid-charge slot
change-detect/commit functions (they store into the `0xAD8F…`/`0xAD9C…`/`0xADAC…`
slot records and, **in AC First**, enqueue changes via `FUN_0009C756`, docs/07). A
few direct scalars are interleaved. These correspond to the ARM-side **AC-charge /
charge-priority / forced-discharge time-window** schedule (dongle holding regs
64–89).

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

### Block 4 (`b300 |= 0x010`)

| off | w | → |
|---|---|---|
| `0x15` | 2 | `0xAD54` (mask) |
| `0x17`/`0x19`/`0x1B` | 2·3 | →`FUN_0009CCBD` (`0x19` rsv) |
| `0x1D`/`0x1F`/`0x21` | 2·3 | →`FUN_0009CD03` (`0x1F` rsv) |
| `0x23` | 2 | `0xAD8C` |
| `0x25` | 2 | `0xAD55` |
| `0x27`/`0x29`/`0x2B` | 2·3 | →`FUN_0009C309` (`0x29` rsv) |

### Block 5 (`b300 |= 0x020`)

| off | w | → |
|---|---|---|
| `0x15` | 2 | `0xAD54` (mask) |
| `0x17`/`0x19`/`0x1B` | 2·3 | →`FUN_0009CD49` (`0x19` rsv) |
| `0x1D`/`0x1F`/`0x21` | 2·3 | →`FUN_0009C7EE` (`0x1F` rsv) |
| `0x23`/`0x25`/`0x27` | 2·3 | →`FUN_0009C01C` (`0x25` rsv) |
| `0x29` | 2 | →`FUN_0009BC08(2, …)` — **AC-First command**, only if `b300 & 1` (block 0 already received) |

### Block 6 (`b300 |= 0x040`)

| off | w | → |
|---|---|---|
| `0x15` | 2 | `0xAD54` (mask) |
| `0x17`/`0x19`/`0x1B` | 2·3 | →`FUN_0009CBEB` (`0x19` rsv) |
| `0x1D`/`0x1F`/`0x21` | 2·3 | →`FUN_0009BFC8` (`0x1F` rsv) |
| `0x23`/`0x25`/`0x27` | 2·3 | →`FUN_0009CC31` (`0x25` rsv) |

**Triplet convention:** the handler sees `(val_b, val_a)` with a reserved word
between; emit the reserved word (0). On-DSP storage/semantics live in the `docs/07`
slot-commit family. Source map: [`docs/10`](../10-dsp-config-field-map.md).
