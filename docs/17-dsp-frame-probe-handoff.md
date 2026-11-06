# Hand-off: BE-mode frame probe — close the regs 64-89 → DSP map

**For the DSP-side agent** (you have `docs/07`/`docs/10` + the DSP image, and
now the ARM image too). This is a ready-to-run ARM-side probe plus the facts to
align it with `FUN_00092EE2`, so the `regs 64-89 → DSP RAM target` map closes
with proof on both ends.

## Why this hand-off exists

`docs/08` first read the ARM↔DSP link as standard EG4-Modbus; your `docs/10`
cross-check ("Is this a standard Modbus read response? — no") showed the DSP
frame is **big-endian, SN-less, block-tagged (id @ `0x14`)**. That cross-check
was right. The ARM-side reason, now proven (see the `docs/08` CORRECTION):

> The ARM frame serializer `sub_0803373c` is **dual-mode**, switched by RAM flag
> **`0x2000aa0b` bit 0**:
> * `bit0 = 0` → **dongle** path: `SN[10]` copied, **little-endian** values
> * `bit0 = 1` → **DSP** path: no SN, **big-endian** values
>
> The earlier ARM emulation forced `bit0 = 0`, so it characterised the *dongle*
> framing. This probe forces `bit0 = 1` (the DSP path).

## What the probe does

`tools/emu_dsp_frame_probe.py` runs the ARM image in Unicorn, drives the frame
builder `sub_08014fec` with `0x2000aa0b = 1` (DSP path), and recovers
**register → frame-offset** by stubbing the per-register getter `fn_ceaa`
(`0x08032000`) to return the register number itself — so every big-endian u16 in
the captured frame *is* its source register number.

Prereqs (from the ARM image): `reference/ceaa-07xx_vE_260214.bin`
(`python3 tools/hex2bin.py <arm>.hex reference/ceaa-07xx_vE_260214.bin`) and
`reference/symbols.csv` (`python3 tools/recurse.py reference/ceaa-07xx_vE_260214.bin --out reference`).

```bash
python3 tools/emu_dsp_frame_probe.py 3 40 40   # func 3 (read holding), group 40-79  -> regs 64-79
python3 tools/emu_dsp_frame_probe.py 3 80 40   # group 80-119                         -> regs 82-89
```

## What it currently shows (ARM side)

The DSP-path (`0x2000aa0b=1`), func-3 read response is **big-endian, SN-less**:

```
off 0x00  addr
off 0x01  func (0x03)
off 0x02  byte count (= count*2)
off 0x03  register values, 2 bytes each, BIG-ENDIAN, in register order
          (… then a 2-byte trailer, likely CRC)
```

so **register N → frame offset `0x03 + (N - start) * 2`**. For the battery
charge/discharge schedule (defs in `include/inv/modbus_map.h`), group 40-79:

| reg | field | BE frame off |
|---|---|---|
| 64 | `HR_CHG_POWER_PCT` | `0x33` |
| 66 | `HR_ACCHG_POWER_PCT` | `0x37` |
| 67 | `HR_ACCHG_SOC_LIMIT` | `0x39` |
| **68** | **`HR_ACCHG_START_0`** | **`0x3b`** |
| 69 | `HR_ACCHG_END_0` | `0x3d` |
| 70-73 | AC-charge win 1/2 | `0x3f`–`0x45` |
| 76-81 | charge-priority wins | `0x4b`–`0x55` |

(regs 82-89 forced-discharge: run the `80 40` group, `0x03 + (N-80)*2`.)

## The open question only you can settle

This is a func-**3 read response** (`values @ 0x03`). It is **not** obviously the
same frame your `FUN_00092EE2` parses, which you documented as **type-`1`**,
18-byte header, **block id @ `0x14`**, payload @ `0x15`, non-register "slot
triplets". Two possibilities — please confirm from the DSP side:

1. **The DSP polls the ARM with func 3/4 (BE)** and `FUN_00092EE2` (or a sibling)
   consumes *this* read response — in which case the block model is really a
   register-range view and the map is simply `reg N → 0x03 + (N-start)*2` above.
2. **The type-1 block frame is a separate message** the ARM emits through a
   *different* builder (not `sub_08014fec`, which only dispatches
   `[RX+1] ∈ {3,4,6,0x10,0x21,0x22,0x23}` — **not** `1`). If so, that builder is
   still unlocated on the ARM side; a good lead is `sub_080258ca` (writes
   `[buf+1]=1`, `[buf+3]=0x36`, status at `+0xd/+0xe`) via `sub_08024dfc`.

**What would decide it (DSP side):** does `FUN_0009E309`/`FUN_00092EE2` read its
input at `buf[0x14]`/`buf[0x15]` (⇒ type-1 block, option 2) or walk values from
`buf[0x03]` after a `func/bytecount` header (⇒ this read response, option 1)?
And is the request the DSP sends a func-3 read, or a type-1 push? Your
`FUN_00096EE8` uplink analysis (`[0]=0x49,[1]=1,[2:3]=0x0036`, filler
`FUN_00092110(buf,0x14)`) suggests option 2 for config — if so, the ARM builder
to pin is the type-1 one, and this probe covers the register-read channel.

## Deliverable

Either (1) confirm `reg N → 0x03 + (N-start)*2` is what the DSP ingests and we're
done, or (2) identify the ARM type-1 builder (or confirm `sub_080258ca`), then we
map each block-`0x15+` slot triplet to its register. Append the resolution to
`docs/10` (DSP-side truth) and drop a one-line pointer here.

## ARM-side reference (addresses)

| what | where |
|---|---|
| frame builder / dispatcher | `sub_08014fec` (`0x08014fec`), on `[RX+1]` |
| BE/LE + SN serializer | `sub_0803373c` (`0x0803373c`); write handler `sub_08033bb4` |
| mode flag (0=dongle LE+SN, 1=DSP BE) | `0x2000aa0b` bit 0 |
| per-register value getter | `fn_ceaa` (`0x08032000`), `r0 = reg` |
| link buffer (USART3 `0x40004800`) | `0x20007490` (RX `[0..0x31F]`, TX `+0x321`) |
| response frame assembled at | `0x20009414`; sent by `sub_08015094` → `sub_0801c370` |
| clock pushed to DSP (separate frame) | `sub_08021df8` → `0x20009754` (`0xA5 0xA5` + Y/M/D h:m:s) |
| candidate type-1 builder | `sub_080258ca` → `sub_08024dfc` |

---

## RESOLUTION (DSP-side + ARM 260214 image) — option 2, type-1 block protocol

Settled: `FUN_00092EE2` ingests the **type-1 block frame** (block id @ `0x14`,
big-endian values @ `0x15`), **not** the func-3 read response. Confirmed on both
ends and written up in **`docs/10` → "ARM-side confirmation (260214 App image)"**.

- The ARM builds the type-1 frame with `FUN_080273b4` (header `[0]=0x41`,
  `[1]=1`, `[3]=0x36`) → `FUN_08026830(buf, 0x14, blockId)` (block id @ `0x14`,
  BE values @ `0x15`); it **rotates the block id** to push the full set.
- The ARM parses the DSP's type-1 telemetry with `FUN_08025ab8(0x14)`; its RX
  SOF check is `0x49` (`FUN_0801bb0e`). SOF asymmetry (`0x41` down / `0x49` up) is
  why the DSP RX never checks `0x49`.
- The candidate `sub_080258ca`/`sub_08024dfc` was in the right region; on the
  260214 build the type-1 builder/parser are `FUN_08026830` / `FUN_08025ab8`.
- **The func-3 BE probe here characterizes a *different* channel** (a register-read
  service), not the config push. The `reg N → DSP RAM` map therefore runs
  register → ARM settings struct (`DAT_080274f0/f4`) → type-1 frame → `FUN_00092EE2`;
  the remaining leg is struct-field → register-number (see `docs/10`).
