# TI C2000 DSP — "AC First" output-priority logic

Status: **recovered from the DSP image by static RE.** First time the C28x
control DSP (previously "out of scope / can't disassemble", see
[`docs/05`](05-dsp-link.md)) has been disassembled and read. The mode selector,
its storage, and the code it gates are identified with high confidence; the
exact power-electronics effect of each gated action is partially characterised
(the DSP has no strings, so everything below is from control-flow + the ARM-side
Modbus map as a Rosetta stone).

> **Scope note.** This is analysis of the proprietary TI DSP image for
> interoperability — understanding the ARM↔DSP contract. We do not reimplement or
> redistribute the DSP firmware; the binary stays out of the tree (see README).

## TL;DR

- **"AC First" is output-priority value `2`.** The ARM exposes it as Modbus
  holding register **145** (`HR_OUTPUT_PRIO_CFG`, `0 = Bat First, 1 = PV First,
  2 = AC First` — see [`include/inv/modbus_map.h`](../include/inv/modbus_map.h)
  and `ch_out_prio[]` in [`src/hmi/hmi_model.c`](../src/hmi/hmi_model.c)).
- In the DSP that setting lives at **data word `0x00ADA8`** (call it
  `g_outputPrio`), in LS5 RAM. The whole control/comms codebase asks **"are we in
  AC First?"** by testing `g_outputPrio == 2`.
- It is almost always paired with an **AC/grid-charge enable bit**: the idiom
  `g_outputPrio == 2 && (g_acChargeFlags & 0x08) == 8` appears **14×** verbatim,
  plus many more `== 2` / `!= 2` / `< 2` tests.
- AC First is **not one function** — it is a config-driven gate. The most
  concrete thing it does: a family of ~20 handlers (`0x9BFC8`…`0x9CD49`) commit
  grid-charge-schedule parameters (AC-charge time windows / SOC / voltage) into
  an action queue **only when AC First is active**.

## How the DSP image was opened (reproducible)

The DSP is a **TI C28x** (C2000). Confirmed device class from the peripheral
map Ghidra labelled: ePWM1–12, 4× ADC (A/B/C/D), CLA, eCAP/eQEP, DACs — an
**F2837x-class** motor/power-control MCU. Flash runs from word `0x80000`.

1. **Disassembler.** Ghidra **12.1.2** + the community SLEIGH processor module
   [`outlandnish/ghidra-tms320c28x`](https://github.com/outlandnish/ghidra-tms320c28x)
   (language `TMS320C28x:LE:32:default`, target F28377D). No mainline Ghidra /
   capstone / objdump supports C28x; this module does.
2. **`.hex` → flat image.** `tools/hex2bin.py <dsp>.hex out.bin --base 0x00100000`.
   The Intel-HEX byte addresses are `2 ×` the C28x **word** address (word
   `0x80000` = byte `0x100000`). 141,304 bytes present — matches the DSP `.bin`
   recorded in the README.
3. **The byte-swap (important).** The vendor image stores each 16-bit word
   **high-byte-first**. Proof: C28x `LCR` (call) opcodes `0x7640–0x767F` number
   **6** in the as-dumped order but **1422** once byte-swapped — a real firmware
   this size is full of `LCR`. So swap byte pairs before import:
   ```python
   d = bytearray(open("out.bin","rb").read())
   s = bytearray(len(d)); s[0::2] = d[1::2]; s[1::2] = d[0::2]
   open("out_swapped.bin","wb").write(s)
   ```
4. **Load + analyse.** Import `out_swapped.bin` as `TMS320C28x:LE:32:default`,
   set image base to word `0x80000`, then run the module's pipeline:
   `SetupF28377D` (map flash/RAM/peripherals), `SeedFunctions` (recovers
   `_c_int00` + call-target/prologue functions), `MarkJumpTables`,
   `MarkDataTables`. Result: **~650 functions**, `_c_int00` recovered, 3 switch
   tables. Image regions (word addresses): header/CRC/vectors `0x80000–0x811FF`,
   a small `0x81C80–0x81FFD`, and the bulk of the code `0x90000–0x9FFFD`.

> Everything below quotes **word** addresses (what Ghidra's listing shows for
> this `wordsize=2` space); `Address.getOffset()` is the byte offset = word × 2.

## The mode selector: `g_outputPrio` @ `0x00ADA8`

`DAT_0000ADA8` is a small-range setting, unpacked from the parameter blob at
`0x00AC80` and **clamped**, defaulting to `0`. It is compared only against `2`
and `< 2` — i.e. "is this the special top value (AC First) or one of the two
lower values (Bat/PV First)?". The identification rests on three independent
facts that all agree:

1. **Range & default.** 3-valued `{0,1,2}`, inited to `0`
   (`DAT_0000ADA8 = 0;` at the reset path).
2. **Value match.** The *only* `{A, B, AC First}` enum anywhere in the system is
   output priority, and **AC First is literally `2`** there (`ch_out_prio[]`,
   reg 145). The DSP tests `== 2` pervasively.
3. **Behaviour match.** The `== 2` branches gate **grid-charging** parameters
   and actions — exactly what "AC First" means (prefer the grid to supply load
   and charge the battery).

### Where it is set — `FUN_00092EE2` (settings deserialiser)

`FUN_00092EE2` walks the packed parameter blob at `&DAT_0000AC80` (the shadow of
the settings the ARM pushes over the inter-processor link, per
[`docs/05`](05-dsp-link.md)) through the field reader `FUN_0009E7C2`, writing the
unpacked config into the `0x00AD??` RAM block:

```
g_outputPrio   = 0x00ADA8   // output priority (0 Bat / 1 PV / 2 AC First)
g_acChargeFlags= 0x00AD84   // flags word; bit 3 (0x08) = AC/grid-charge enable
g_slotEnable   = 0x00AD54   // per-parameter "this slot active" bitmask
g_slotDirty    = 0x00AD56   // per-parameter "pending change" status
// grid-charge schedule record fields: 0x00AD8F..0x00AD97, 0x00AD9C..0x00ADAF ...
```

Right after unpacking it runs `if (g_outputPrio != 2 && g_outputPrio < 2 && …)`
— the explicit "**not** AC First (so Bat/PV First)" branch.

## What AC First gates

### 1. The recurring enable test (14× verbatim)

```c
g_outputPrio == 2 && (g_acChargeFlags & 8) == 8
```

Read as **"AC First is selected AND grid charging is enabled."** Each occurrence
is additionally qualified by one bit of `g_slotEnable (0x00AD54)` — `0x4`, `0x8`,
`0x10`, `0x20` … `0x4000`, `0x800`, etc. — i.e. one bit per grid-charge
parameter slot.

### 2. The commit family `0x9BFC8 … 0x9CD49`

~20 near-identical handlers (`FUN_0009BFC8`, `FUN_0009C01C`, `FUN_0009C070`,
`FUN_0009C0C4`, … `FUN_0009CD49`). Each owns one 4-field parameter record
(two 16-bit + two bytes, e.g. `0x00AD8F..92`, `0x00AD9C..9F`, `0x00ADAC..AF`),
with a dirty bit in `g_slotDirty (0x00AD56)` and an enable bit in
`g_slotEnable (0x00AD54)`. Shape:

```c
if (record matches the stored copy) {
    g_slotDirty &= ~slotbit;              // unchanged -> clear pending
} else if ((g_slotDirty & slotbit) == 0) {
    store the new record;
    if (g_acEnabled && counter > 1 &&
        g_slotEnable & slotbit &&
        g_outputPrio == 2 && (g_acChargeFlags & 8) == 8) {   // <-- AC First gate
        FUN_0009C756(hi, lo, 4);          // enqueue the change for action
    }
}
```

`FUN_0009C756` (20 callers) is the enqueue: it copies the 4-word record into a
**15-deep ring buffer at `0x00AA94`** (stride 4, count at `0x00AAD7`). So in AC
First mode a changed grid-charge parameter is **queued to take effect**; outside
AC First the same change is stored but **never queued** — the schedule is inert
unless AC First is chosen. These records correspond to the ARM-side "AC Charge
Time / AC Charge Battery SOC / AC Charge Battery Voltage" settings (the
`sub_08005bec` string cluster in [`docs/03`](03-function-map.md)/`reference/`).

### 3. Other AC-First-only paths

- **`FUN_000933A1`** — an inter-processor **sub-command handler**: after copying
  the frame to a stack buffer it does `if (g_outputPrio == 2) { … }` and only
  then decodes a 1–12 sub-type field (`(hdr & 0x3E0) >> 5`) and applies the
  grid-charge records. Non-AC-First frames of this class are ignored.
- **`FUN_00096B10`** — a periodic **sequencer** (counter `g_seq = 0x00AD0D`,
  steps 1..N). Its reset guard is
  `((g_acChargeFlags & 8) == 0 || g_outputPrio != 2) && (g_seq > 1 || g_outputPrio != 2)`
  → the sequence only advances when AC First + grid-charge-enable hold.
- **`FUN_0009BC08`** — a command-acceptance path that only applies its action
  (`FUN_0009C756(…,4)`) under `g_outputPrio == 2 && (g_acChargeFlags & 8) == 8`.

In total **18 functions** reference `g_outputPrio` directly.

## Confidence & open questions

- **High confidence:** `0x00ADA8` is the output-priority selector and `== 2` is
  AC First; `FUN_00092EE2` sets it; the `0x9BFC8…0x9CD49` family + `FUN_0009C756`
  is the AC-First-gated grid-charge-parameter commit path. The three
  lines of evidence (range/default, value match to reg 145, grid-charge
  behaviour) are mutually corroborating.
- **Medium confidence:** the exact meaning of each companion field —
  `g_acChargeFlags (0x00AD84)` bit 3 read as "AC/grid-charge enable",
  `g_slotEnable (0x00AD54)` as the per-slot enable mask. Named from behaviour,
  not proven against a register map.
- **Not yet pinned:** the final power-electronics action — i.e. what consumes
  the `0x00AA94` queue and turns a queued grid-charge record into ePWM / current
  setpoints. That is the queue-drain side and the next thing to trace. The
  byte-exact offset of reg 145 inside the `0x00AC80` blob is also not mapped
  field-by-field (it was identified by value/behaviour, not by blob arithmetic).
- **Caveat:** the SLEIGH module is community/WIP ("verify against TI's
  `dis2000`"). The logic above rests on very common, well-tested instructions
  (loads, `CMP`, conditional branches), not exotic FPU/TMU forms, so decode risk
  here is low — but a hardware or `dis2000` cross-check is the standard next step.

## Addresses quick-reference (word addresses)

| Symbol | Addr | Meaning |
|---|---|---|
| `g_outputPrio` | `0x00ADA8` | output priority: `0` Bat First, `1` PV First, **`2` AC First** |
| `g_acChargeFlags` | `0x00AD84` | flags; **bit 3 (`0x08`)** = AC/grid-charge enable |
| `g_slotEnable` | `0x00AD54` | per-parameter enable bitmask |
| `g_slotDirty` | `0x00AD56` | per-parameter pending-change bitmask |
| settings blob | `0x00AC80` | packed parameter image from the ARM link |
| action queue | `0x00AA94` | 15× 4-word ring; count at `0x00AAD7` |
| `FUN_00092EE2` | `0x92EE2` | settings deserialiser (writes `g_outputPrio`) |
| `FUN_000933A1` | `0x933A1` | AC-First-gated link sub-command handler |
| `FUN_00096B10` | `0x96B10` | AC-First-only periodic sequencer |
| `FUN_0009BFC8`…`0x9CD49` | — | grid-charge parameter commit family |
| `FUN_0009C756` | `0x9C756` | enqueue a 4-word record to `0x00AA94` |
