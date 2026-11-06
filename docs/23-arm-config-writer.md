# ARM config storage — the writer side & per-slot field map

> **Authoritative wiring:** the SPI1↔config-flash link is distilled in [`docs/wiring/ARM-SPI1-flash.md`](wiring/ARM-SPI1-flash.md). This doc remains the write-side detail and per-slot field map.

[`docs/21`](21-arm-config-flash.md) reversed the **read** side of the factory
ARM's settings store: an external SPI NOR flash holding a journaled, wear-levelled
set of **six 8 KB slots**, each a ring of 256-byte CRC-protected records, loaded
at boot by `sub_0801683C`. It left three things open: the **writer** (how a record
is formed and committed), the **per-slot payload layout** (what each slot's 250
settings bytes actually are), and the **internal-flash defaults**. This note closes
all three.

Findings are from the same `ceaa-07xx` 12000XP "com" image as docs/21 (App vectors
@`0x08005000`; flat image via `make factory`). Two methods were used:

1. **Static** — disassembly of the writer and its callers (`tools/disres.py`,
   `tools/ramxref.py` against the flat image).
2. **Dynamic** — the `arm_sim` Modbus "dongle" harness (`tests/arm_sim_modbus.py`)
   boots the *factory image* and writes a holding register over the real UART; we
   diff the six RAM record images before/after to see exactly which record byte a
   given register lands in. This is what produced the field map below.

## Record format (confirmed from the writer)

The writer `sub_080164bc(slot)` forms a record in RAM and matches docs/21's layout
byte-for-byte, now proven from the write side:

```
offset  size  field
0x00    250   payload (the settings for this slot)
0xFA      2   CRC-16/MODBUS of payload[0x00..0xFA], little-endian  (sub_080160BC)
0xFC      3   padding (written 0xA5)
0xFF      1   0xA5  "record written" marker
```

`sub_080164bc` computes the CRC over `[0x00:0xFA]`, stores it at `+0xFA`, then
writes the word `0xA5A5A5A5` at `+0xFC` (so the marker at `+0xFF` is `0xA5` and the
three pad bytes are `0xA5` too).

## The six in-RAM record images

The ARM keeps each slot's live record as a **256-byte RAM buffer**; these are the
data structures that get serialized to flash. They are contiguous and sit directly
below the DSP telemetry struct (`0x2000ce5c`, [`docs/18`](18-power-path-relays.md)):

| Slot | RAM record image | SPI flash region | Role |
|---|---|---|---|
| 0 | `0x2000c85c` | `0x000000–0x001FFF` | **main settings** (+ internal-flash mirror) |
| 1 | `0x2000c95c` | `0x002000–0x003FFF` | settings struct B (mirrored to slot 4) |
| 2 | `0x2000cb5c` | `0x004000–0x005FFF` | small identity block |
| 3 | `0x2000cc5c` | `0x006000–0x007FFF` | small identity block (twin of slot 2) |
| 4 | `0x2000ca5c` | `0x008000–0x009FFF` | backup copy of slot 1 |
| 5 | `0x2000cd5c` | `0x00A000–0x00BFFF` | **grid/protection settings** (+ internal-flash mirror) |

The slot→flash map is the per-slot descriptor table at `0x080057b8` (12 bytes/entry
= `{index, flash_base, flash_end}`), which matches docs/21's layout exactly.

## The writer path

```
sub_080164bc  commit one record to a slot's ring
   ^ sub_0801ce32   write-one-slot (per-slot dispatch, slot1→slot4 mirror, failure bits @0x2000db51)
   ^ sub_0801cfbc   flush: for each dirty slot, (re)serialize + write
   ^ sub_0801d2ec   periodic config task
   ^ sub_0802e2f0   task setup
```

`sub_080164bc(slot)` does, in order:

1. **Finalize** the RAM record (CRC `+0xFA`, `0xA5A5A5A5` `+0xFC`), as above.
2. **Page-program** the 256-byte record to the ring's current write address
   (`sub_0801c90e`, which splits into 256-byte page programs via `sub_0801c872`;
   WREN + `0x02` program).
3. **Read-back verify**: read the just-written page (`sub_0801cace`) into scratch
   `0x2000b2cc` and checksum-compare (`sub_080161a8`) against the source; a
   mismatch marks the write failed.
4. **Advance the ring** by `0x100`; on reaching the region bounds (`flash_base`/
   `flash_end` from the descriptor table) it **erases a 4 KB sector**
   (`sub_0801c7b2`) and wraps. This confirms the journaled-ring + 4 KB-sector-erase
   model behind the flash-lifetime estimate (~32 × endurance records/slot).
5. If `slot == 0 || slot == 5`, call `sub_0801d1d8` (internal-flash mirror, below).

The save is **dirty-flag driven**, not called on every setting change: a setting
write marks the slot dirty; `sub_0801cfbc` (gated on request flags at `0x2000d890`/
`0x2000d9c8`/`0x2000db4f`) flushes the dirty slots from the periodic task.

### Slot 1 ↔ slot 4 mirror

When slot 1 is saved, `sub_0801ce32` first `memcpy`s the live slot-1 record
(`0x2000c95c`) into the slot-4 buffer (`0x2000ca5c`, `sub_08005130` = memcpy) and
writes both — slot 4 is a **redundant backup of slot 1**, not an independent
settings area.

## Internal-flash mirror for slots 0 and 5

docs/21 found that slots 0 and 5 fall back to compiled-in default records in the
MCU's internal flash (`0x0807F800` / `0x0807F900`) and noted those pages are past
the end of the dump. The writer shows these are **not static factory data** — they
are a firmware-maintained mirror:

- `sub_0801d1d8` (called after every slot-0/5 save) **erases and re-programs**
  `0x0807F800` from the slot-0 image and `0x0807F900` from the slot-5 image (internal-flash
  driver `sub_08036b38/ba4/ce0/b58/c4c`).
- `sub_0801d144` (the loader's fallback) copies that internal page into a scratch
  buffer (`0x2000c65c`), validates marker + CRC, and only then accepts it.

So slots 0 and 5 always have a last-known-good copy in internal flash even if the
SPI chip is blank or corrupt; the other slots do not. (A whole-image scan for any
embedded valid record — marker + matching CRC — finds none, confirming there is no
other compiled-in default page in the dump.)

## Per-slot payload field map

Recovered by driving Modbus writes into the factory image and observing the record
byte that changes (dynamic probe above). Offsets are into the slot's 250-byte
payload. 16-bit fields are little-endian; register names are from the EG4 18KPV-12LV
Modbus spec. Values are stored in the register's documented wire units unless noted.

> **Method & confidence.** Every row was confirmed *dynamically*: a Modbus `0x06`
> write of a known value into the booted factory image, then reading back the
> record byte whose new value matches what was written (`tests/arm_sim_modbus.py`
> + a byte-diff of the six record images). 56 registers are pinned this way.
> Fields are 16-bit little-endian; "stored" is the value observed in the record
> after writing, and `×10` marks a register the firmware scales before storing.
> The two slots below are the only ones that received `0x06` settings writes — the
> user-facing settings live in **slot 0** and **slot 5**.

#### Slot 0 — main inverter/working settings

| HR | Field | Offset | Width | stored |
|---|---|---|---|---|
| 15 | ComAddr | `+0x00` | 2B | 30 |
| 21 | FuncEn (bitmask) | `+0x13` | 2B | 309 |
| 110 | FunctionEn1 (bitmask) | `+0x15` | 2B | 21 |
| 20 | PVInputModel | `+0x18` | 2B | 3 |
| 112 | SetSystemType | `+0x1b` | 2B | 1 |
| 119 | wCT_PowerOffset | `+0x2f` | 2B | 100 |
| 120 | stSysEnable (bitmask) | `+0x33` | 2B | 21 |
| 68 | ACChgStart (hh:mm) | `+0x3a` | 2B | 1541 |
| 69 | ACChgEnd | `+0x3c` | 2B | 2055 |
| 70 | ACChgStart1 | `+0x3e` | 2B | 2310 |
| 71 | ACChgEnd1 | `+0x40` | 2B | 2824 |
| 72 | ACChgStart2 | `+0x42` | 2B | 3338 |
| 73 | ACChgEnd2 | `+0x44` | 2B | 3852 |
| 152 | ACFirstStart0 | `+0x64` | 2B | — |
| 153 | ACFirstEnd0 | `+0x66` | 2B | — |
| 154 | ACFirstStart1 | `+0x68` | 2B | — |
| 155 | ACFirstEnd1 | `+0x6a` | 2B | — |
| 156 | ACFirstStart2 | `+0x6c` | 2B | — |
| 157 | ACFirstEnd2 | `+0x6e` | 2B | — |
| 147 | Battery capacity | `+0x70` | 2B | 100 |
| 99 | ChargeVoltRef (lead-acid) | `+0x74` | 2B | 560 |
| 151 | EqualizationTime | `+0x7c` | 2B | 4 |
| 101 | ChargeCurr | `+0x8c` | 2B | 420 (×10) |
| 102 | DischgCurr | `+0x8e` | 2B | 430 (×10) |
| 103 | MaxBackFlow | `+0x9c` | 2B | 500 (×10) |
| 105 | EOD | `+0x9e` | 2B | 20 |
| 107 | TemprUpperLimitDischg | `+0xa1` | 2B | 310 |
| 109 | TemprUpperLimitChg | `+0xa5` | 2B | 330 |

#### Slot 5 — grid-code protection & power-command settings

| HR | Field | Offset | Width | stored |
|---|---|---|---|---|
| 60 | ActivePowerPercentCMD | `+0x00` | **1B** | 55 |
| 61 | ReactivePowerPercentCMD | `+0x01` | **1B** | 30 |
| 64 | ChargePowerPercentCMD | `+0x02` | **1B** | 51 |
| 65 | DischgPowerPercentCMD | `+0x03` | **1B** | 52 |
| 66 | ACChgPowerCMD | `+0x04` | **1B** | 53 |
| 23 | ConnectTime | `+0x05` | **1B** | 120 |
| 59 | ReactivePowerCMDType | `+0x07` | **1B** | 3 |
| 30 | GridVoltLimit1High | `+0x0a` | 2B | 2700 |
| 34 | GridVoltLimit2High | `+0x0c` | 2B | 2800 |
| 38 | GridVoltLimit3High | `+0x0e` | 2B | 2900 |
| 29 | GridVoltLimit1Low | `+0x10` | 2B | 1800 |
| 33 | GridVoltLimit2Low | `+0x12` | 2B | 1700 |
| 37 | GridVoltLimit3Low | `+0x14` | 2B | 1600 |
| 32 | GridVoltLimit1HighTime | `+0x16` | 2B | 110 |
| 36 | GridVoltLimit2HighTime | `+0x18` | 2B | 130 |
| 40 | GridVoltLimit3HighTime | `+0x1a` | 2B | 150 |
| 31 | GridVoltLimit1LowTime | `+0x1c` | 2B | 100 |
| 35 | GridVoltLimit2LowTime | `+0x1e` | 2B | 120 |
| 39 | GridVoltLimit3LowTime | `+0x20` | 2B | 140 |
| 43 | GridFreqLimit1High | `+0x22` | 2B | 5300 |
| 47 | GridFreqLimit2High | `+0x24` | 2B | 5400 |
| 51 | GridFreqLimit3High | `+0x26` | 2B | 5500 |
| 46 | GridFreqLimit2Low | `+0x2a` | 2B | 4600 |
| 45 | GridFreqLimit1HighTime | `+0x2e` | 2B | 170 |
| 49 | GridFreqLimit2HighTime | `+0x30` | 2B | 190 |
| 53 | GridFreqLimit3HighTime | `+0x32` | 2B | 210 |
| 44 | GridFreqLimit1LowTime | `+0x34` | 2B | 160 |
| 48 | GridFreqLimit2LowTime | `+0x36` | 2B | 180 |
| 52 | GridFreqLimit3LowTime | `+0x38` | 2B | 200 |
| 26 | GridVoltConnHigh | `+0x3a` | 2B | 2600 |
| 25 | GridVoltConnLow | `+0x3c` | 2B | 2000 |
| 28 | GridFreqConnHigh | `+0x3e` | 2B | 5200 |
| 27 | GridFreqConnLow | `+0x40` | 2B | 4800 |
| 75 | ChgFirstSOCLimit | `+0x7a` | 2B | 82 |

### Width correction & harness notes (task T03, cross-image oracle)

Re-checking the full table with a **cross-image round-trip oracle** (ours writes a
record, the factory reads it back, and vice-versa — `tests/test_persist_crossimage.py`,
machine-readable table `include/inv/settings_map.h`) settled two things this doc
first got wrong and surfaced a couple of factory behaviours:

- **Slot-5 `+0x00..+0x07` are 1-byte fields, not "2B".** The power-command block
  (HR 60/61/64/65/66/23/59) is a packed run of single bytes — the offsets advance
  by 1, and each value fits a byte. The "2B" above was a transcription default;
  corrected in the table. The grid-code block from `+0x0a` on is genuinely 2B.
- **HR 109 (TemprUpperLimitChg) is at `+0xa5`, not `+0xa4`.** Writing a distinct
  value and locating it in the record puts it at `+0xa5`/`+0xa6`; `+0xa4` holds an
  unrelated byte. Corrected above.
- **HR 112 (SetSystemType): value 2 (slave) is rejected** by the factory in this
  black-box harness (no `0x06` echo); value 1 (master) is accepted. The write is
  gated (parallel-mode precondition). See [`docs/31`](31-factory-quirks.md).
- **HR 21 (FuncEn) does not read back verbatim** — the factory reports it with an
  extra capability bit set (`stored | 0x200`). Our stored bits all survive; the
  read is a merge, not an echo. See [`docs/31`](31-factory-quirks.md).
- **Harness shape (not a device fact):** the emulated factory serves exactly one
  dongle *write* per boot (a settings write blocks further dongle service until
  reboot), and it **re-journals its loaded config early in boot**, which wedges the
  dongle for the rest of that boot whenever it boots on a device *our* firmware has
  written. So the oracle cannot drive the factory to read back a 62-register flash
  our firmware produced (that is a T02 dependency — the factory RTOS in the sim).
  Instead it (a) checks our firmware writes the whole table byte-exact to this
  layout and byte-identical to the factory's own record per storage class, and
  (b) does the *live* round-trip the other way — the factory writes, our firmware
  reads back — one register per storage class. All 62 rows (the 56 above + the 6
  AC-First windows) are covered.

**Not resolved dynamically.** ~47 settings registers are *rejected* by the factory
firmware in this black-box harness (no `0x06` echo), so their offsets are not pinned
here: the Q(V)/PF reactive block (54–58, 92–97), the charge-first and
forced-discharge schedules (74, 76–89), lead-acid cut/temperature (100, 106, 108),
and most of the 115–143 / 169+ range. These are almost certainly gated on cross-field
validation (e.g. `V1L < V1H`), inverter run-mode, or the `0x10` multi-write path;
pinning them needs a preconditioned write or a static read of the write dispatch. A
further ~12 echoed but their exact offset is still ambiguous (24, 42, 62, 63, 90, 91,
126–131). Both sets are follow-up work — the method above resolves each one once the
precondition is met.


### Reading the map

- **Slot 0** carries the bulk of the *inverter/working* settings (functions,
  PV-input model, comms address, charge/discharge currents, lead-acid thresholds,
  …): ~122 distinct fields over the full `0x00–0xF8` payload.
- **Slot 5** carries the **grid-code protection** block — connection limits and the
  three-level over/under voltage & frequency trip points and times (`+0x0a–0x40`) —
  plus a small packed region of active/reactive/charge/discharge power-command
  percentages and the reactive-command type (`+0x00–0x07`). A second dense `u16`
  struct.
- **Slot 1** holds a further settings group (serialized from a working struct at
  `0x2000d850` at save time — docs/10's "ARM settings struct").
- **Slots 2 and 3** are small (~11 bytes) and written byte-by-byte
  (`sub_08019d24` / `sub_0801a59c`), consistent with the 10-byte device **serial
  number** (HR 2–6 `SN[10]`) held in two copies.

## Reset-to-default (HR 11 `ResetSetting`)

HR 11 is a bit-mask of one-shot actions (bit 0 `EnergyRecordClr`, **bit 1
`AlltoDefault`**, bit 2 `AdjRatioClr`, bit 3 `FaultRecordClr`, bit 4 `MonitorData`,
bits 5/6 BMS charge/discharge switch, bit 7 `InvReboot`). It is handled
**flag-driven**: the write sets request flags that the super-loop (`sub_0801b3dc`)
subsystem services consume — e.g. bit 7 is serviced by `sub_08035fe2`, which issues
a Cortex-M `SYSRESETREQ` (AIRCR `0xE000ED0C` ← `0x05FA0004`). `AlltoDefault`
reinitializes the settings structs in code and marks the slots dirty, so the writer
above flushes the restored records (slots 0/5 also refresh their internal-flash
mirror). There is no compiled-in default *record* to copy; the defaults are built
field-by-field.

## Open questions

- The exact code path that **populates** each `AlltoDefault` default value (the
  per-field default constants) is not yet enumerated.
- A handful of registers (time HR 12–14, language HR 16) did not land in the six
  slots in the probe — time is RTC-backed and some comms/display settings may live
  outside the slot images; these are marked accordingly in the map.
- Slot 2 vs slot 3: both hold the same small block; whether they are
  primary/backup or two distinct identity fields is not yet pinned.
