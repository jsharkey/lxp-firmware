# Who persists settings — DSP vs ARM; and where the clock comes from

Question under test: does the **DSP** keep operating settings (and the wall
clock) in storage that survives a long power-off, or does the **ARM** own
persistence and re-seed the DSP after every boot?

**Answer: the DSP persists nothing across a power cycle.** It has no non-volatile
settings storage and no battery-/power-backed clock. All of its configuration
RAM is volatile and, at boot, the DSP sits waiting for the ARM to push the
complete settings set (see [`docs/08`](08-arm-dsp-config-protocol.md)). The ARM
is therefore the authority for both **persistence** and **timekeeping**
(the ARM's battery-backed STM32 RTC — [`docs/05`](05-dsp-link.md)).

Method: static RE of the DSP image (Ghidra + `ghidra-tms320c28x`,
[`docs/07`](07-dsp-ac-first-mode.md)) — a full peripheral/driver inventory of the
~650 recovered functions. A hardware/schematic check would confirm the board
matches, but the firmware carries no driver for any of the parts that would be
needed, which is itself strong evidence.

## 1. Persistent storage — none is present

Every off-chip NV option was checked for an actual **driver** (not just a mapped
peripheral frame):

| Interface | Finding | Evidence |
|---|---|---|
| **SPI-A/B/C** (`0x6100/10/20`) | **unused** | zero register accesses, zero base-address loads anywhere in the image — no SPI flash / SPI EEPROM / SPI RTC |
| **I2C-A** (`0x7900`) | **not functionally used** | the frame is only *parked* during the big GPIO/peripheral init (`I2CIER/STR/CLK/CNT` written once inside `FUN_0009420A`); there is **no** write to `I2CSAR` (slave address), `I2CMDR` (start/mode) or `I2CDXR` (TX data) — i.e. no master transaction is ever issued, so there is no I2C EEPROM/RTC on the bus |
| **I2C-B**, **McBSP** | **unused** | no accesses (the 22 `#0x6000` hits are the bit-mask immediate `0x6000` in `AND/OR`, not a McBSP base) |
| **EMIF** external memory | **unused** | no external-window symbols (`_DAT_8xxxxxxx`) and no EMIF config-register writes — no parallel NOR/SRAM |
| **Internal flash** program/erase | **bootloader only** | the flash API (`FUN_0000C47B` program / `FUN_0000C6E3` erase / `FUN_0000C792`) is called **only** from the SCI-B bootloader `FUN_00080AA8` — the firmware-update path ([`docs/05`](05-dsp-link.md)). No *runtime* code writes flash, so settings are **not** journaled to a flash sector. |

**The only non-volatile content on the DSP is its own firmware image**, in
internal flash, rewritten solely by the ARM-driven `0x21/0x22/0x23` update
sequence. There is no settings region, no EEPROM, no SPI flash.

### The config RAM is volatile and boot-empty

The settings the DSP runs on live in plain data RAM (the `0x00AB??`/`0x00AD??`/
`0x00B2??` block — e.g. output priority at `0x00ADA8`). On F2837x this SRAM is
not retained across power-off. At startup the receive buffer is cleared
(`FUN_0009EE62` zeros `0x00AC80`) and the comms task waits until **every** config
block has been received — it only marks configuration valid once all of the
per-block "received" bits `0x001…0x200` are set in `DAT_0000b300`
([`docs/08`](08-arm-dsp-config-protocol.md) §proofs). A device that restored its
own settings from NV storage would not boot up blocked on a full re-push from the
peer. This is the behavioural fingerprint of a **stateless slave**.

So: **the ARM stores the settings; the DSP is re-provisioned over the link on
every boot.**

## 2. The clock — no power-off survival; the DSP keeps no wall time

- **No RTC peripheral.** The C28x/F2837x family has no on-chip real-time clock,
  and nothing here adds one off-chip: an external RTC would sit on SPI or I2C,
  both of which have no driver (above).
- **Timers are free-running, not dated.** `CPU_TIMER0` is configured with
  `PRD = 0xFFFFFFFF` and left to free-run; it is **read in exactly one place**
  (`FUN_0009D592`), where it is XOR-mixed with the ePWM counters to make a seed
  value — used as entropy, **not** as a timestamp. It resets to 0 at every boot.
- **No calendar is maintained.** There is no seconds→minutes→hours→date rollover
  logic and no BCD/`year` handling in the image; the DSP never assembles or
  stores a wall-clock time.

**Conclusion:** the DSP has no clock that survives power-off, and in fact does
not track time-of-day at all. Any time-of-day behaviour (e.g. AC-charge time
windows) is owned by the ARM, which has the battery-backed RTC and pushes
settings/commands to the DSP. The DSP's own real-time control uses only elapsed
counts (ePWM/timer), which are relative and reset each boot — exactly what a
power-electronics inner loop needs, and nothing that needs to know the date.

> Note on time-of-day evaluation: the DSP stores the grid-charge time-window
> *parameters* it is pushed (block 0), detects when they change, and queues those
> changes back toward the ARM (`FUN_0009C756` enqueue → `FUN_0009DFB3` dequeue →
> uplink), but it has no local clock to compare them against. The window decision
> itself therefore rests with the ARM. Confirming the exact split of the
> window-evaluation math is the one open follow-up here.

## 3. Implication for the system

- **ARM = persistence + timekeeper + config master.** It holds the saved
  settings (and the RTC), and on each boot streams the full settings image to the
  DSP, then keeps re-sending it (the DSP diffs for changes — [`docs/08`](08-arm-dsp-config-protocol.md)).
- **DSP = stateless real-time executor.** Across a power cycle it keeps only its
  firmware; everything else (settings, time) arrives from the ARM after boot.
- Practical consequence: pulling the DSP's power loses no user configuration
  (the ARM restores it); pulling the **ARM's** backup power is what would lose
  settings/clock. A replacement/blank DSP needs no settings restore — the ARM
  provisions it on first boot.

## Confidence & caveats

- **High confidence (firmware-level):** no SPI/I2C/McBSP/EMIF storage driver; no
  runtime internal-flash writes; config RAM is volatile and boot-empty with a
  full-set wait; no RTC peripheral/driver; timers free-running.
- The "I2C not used" verdict rests on the **absence** of `I2CSAR/I2CMDR/I2CDXR`
  activity — a parked peripheral frame, not a bus device. If a later build added
  an I2C device it would show those registers.
- Static RE cannot see the board. The conclusions are about what the *firmware*
  can do; a schematic/photo would corroborate "no SPI-flash/EEPROM/RTC chip is
  fitted," but the firmware would have to drive one for it to matter, and it does
  not.

## Reference (word addresses / DSP)

| symbol | addr | role |
|---|---|---|
| `FUN_00080AA8` | `0x80AA8` | SCI-B bootloader; **only** caller of the flash program/erase API |
| `FUN_0000C47B` / `C6E3` / `C792` | `0xC47B`/`0xC6E3`/`0xC792` | RAM-resident flash program / erase API (update-only) |
| `FUN_0009420A` | `0x9420A` | GPIO/peripheral init; parks the I2C-A frame (no transactions) |
| `CPU_TIMER0` | `0xC00` | free-running counter (`PRD=0xFFFFFFFF`); read once as a seed |
| `FUN_0009D592` | `0x9D592` | the sole `CPU_TIMER0_TIM` reader (entropy seed, not time) |
| `DAT_0000AC80` | `0xAC80` | volatile RX/config buffer, cleared at boot |
| `DAT_0000B300` | `0xB300` | per-block "config received" completeness bits (boot-empty) |
