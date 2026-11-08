# ARM SRAM budget — how much RAM is free when booted (factory vs ours)

How much of the com-MCU's SRAM is still free for new features once the firmware
has booted? Measured dynamically for **both** firmwares. Short answer:

| firmware | static `.data+.bss` | used (booted) | **free** | of 64 KB |
|---|---|---|---|---|
| **factory** (`ceaa-07xx_vE_260214.bin`) | ≈ 55.0 KB | 55.2 KB | **≈ 8.8 KB** | ≈ 86 % used |
| **ours** (`build/firmware.bin`, main @ `819ed68`) | 4.3 KB | 4.9 KB | **≈ 59.1 KB** | ≈ 8 % used |

So the factory firmware is **nearly RAM-full** (~9 KB headroom), while ours —
even with the current feature set — uses ~5 KB and has **~59 KB free**. There is
ample SRAM for new features on our side.

## The part and the total

The com MCU is an **STM32F103VE** (Cortex-M3, 100-pin "V", high-density "E"):
**512 KB flash @ `0x08000000`, 64 KB SRAM @ `0x20000000`** (`0x20000000`–
`0x2000FFFF`, 65536 B).

Confidence: **high, inferred** — not read off a schematic/markings. Evidence:
GPIO ports **A–E** are configured ([`docs/16`](16-arm-io-map.md)), which is the
100-pin "V" package; the App image occupies flash up to ~`0x0807F800`, i.e. a
512 KB "xE" part; and STM32F103x**E** pairs 512 KB flash with 64 KB SRAM. The
reset vector's initial-SP values land inside `0x20000000+64 KB` for both images,
consistent with 64 KB. (The ldscript still carries an "adjust once confirmed
from the schematic" note — this doesn't change the measured free-RAM below, only
its proportion of the whole.)

## Method (dynamic, emulated)

`tools/ramfootprint.py` (Unicorn, via `tools/arm_sim.py`):

1. Fill all 64 KB of SRAM with a **per-word address sentinel** (`mem[a] = a`).
2. Boot the image from its own reset vector — the C startup then zeroes `.bss`
   and copies `.data` from flash — with a provisioned config flash attached
   (clears the factory boot gate; it is SPI NOR, not MCU SRAM) and SysTick
   firing.
3. Run the super-loop for several million instructions.
4. Read SRAM back: a word **still equal to its own address** was never written →
   **free**. Everything else is `.data` + `.bss` + whatever the stack and any
   runtime buffers touched.

```
python3 tools/ramfootprint.py reference/ceaa-07xx_vE_260214.bin 2000000 6000000
python3 tools/ramfootprint.py build/firmware.bin                 6000000 6000000
```

The footprint is **stable**: identical after boot and after exercising the
Modbus comms path, so it is static-dominated, not an artifact of how long we ran
or how deep a one-off stack excursion went.

**Caveats.** (a) It counts **writes** — a byte only *read*, or reserved inside a
stack frame but never written, reads as "free", so the stack's true worst case
can dip below the observed low-water. Leave margin; don't spend the last KB. (b)
We have no factory **symbol table**, so the factory `.data`/`.bss` split is read
off the *runtime* image (zeroed vs initialised bytes), not a linker map. The
`static` column is exact for ours (from the map) and measured for the factory.

## Factory — `ceaa-07xx_vE_260214.bin`

```
initial SP        : 0x2000dfd8
static .data+.bss : 0x20000000 .. 0x2000dbd8   56280 B (55.0 KB)
used (booted)     : 56512 B (55.2 KB)
free (untouched)  :  9024 B ( 8.8 KB)
  0x2000dbd8..0x2000def0    792 B  (0.8 KB)  below SP  — headroom above static, under the stack
  0x2000dfd8..0x20010000   8232 B  (8.0 KB)  above SP  — never used (stack grows *down* from SP)
```

- **Static ≈ 55 KB** fills `0x20000000`–`0x2000dbd8`. Of it, ≈ 49 KB reads back
  as zero (`.bss`) and ≈ 6 KB is initialised/written (`.data` + boot-populated
  tables). This is the dominant consumer — a mature, feature-complete firmware
  with large static buffers (config mirrors, telemetry, HMI, comms, logging, …).
- **Stack** grows down from `0x2000dfd8`; observed writes reach only ~`0x2000def0`
  (~0.2 KB), with the 0.8 KB gap below it as headroom before the static block.
- **Free ≈ 8.8 KB**, of which the solid **8 KB sits *above* the stack top**
  (`0x2000dfd8`–`0x20010000`) and is never touched. The factory deliberately
  parks SP at `0x2000dfd8`, not the 64 KB top — it has ~55 KB of static and only
  ~1 KB of stack slack, so RAM is genuinely tight on the factory side.

## Ours — `build/firmware.bin` (main @ `819ed68`)

```
initial SP        : 0x20010000   (the 64 KB top)
static .data+.bss : 0x20000000 .. 0x2000112c   4396 B (4.3 KB)   (.data 144 B, .bss 4252 B — from the map)
used (booted)     :  5004 B ( 4.9 KB)
free (untouched)  : 60532 B (59.1 KB)
  0x2000112c..0x2000fd30  60420 B (59.0 KB)  below SP  — one contiguous free pool
```

- **Static = 4.3 KB** (`.data` 144 B + `.bss` 4252 B, `_ebss = 0x2000112c` from
  `build/firmware.map`).
- **Stack** grows down from the 64 KB top; observed low-water ~`0x2000fd30`
  (~0.7 KB).
- **Free ≈ 59 KB**, one contiguous block between the top of `.bss` and the stack.
  Because we control the linker, essentially all of it is usable for new globals
  / buffers (leaving stack margin).

## Takeaway for feature planning

- **Ours has ~59 KB of slack** today — SRAM is not the constraint for new
  features ([`docs/38`](38-oss-feature-ideas.md)). Flash (512 KB, ~21 KB used)
  is even less of one.
- **The factory runs near full (~9 KB free).** Useful context: it explains the
  tight stack placement, and means any factory-side behaviour we emulate should
  not assume spare RAM there. **Where its ~55 KB of static actually goes — and
  whether any of our buffers are under-sized against it — is the open question;
  [`docs/46`](46-factory-ram-breakdown-plan.md) is the plan to break it down.**
- Re-run `tools/ramfootprint.py` after a feature lands to track the budget; the
  `static` figure from `build/firmware.map` moves one-for-one with new globals.
