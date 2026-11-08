# 12000XP firmware revisions over time — `ceaa-05xx` vs `ceaa-07xx`

This compares two ARM "com" firmware revisions for the **same** EG4 12000XP unit:

| | older | newer |
|---|---|---|
| Image | `…_ceaa-05xx_com_vE_250325.hex` | `…_ceaa-07xx_vE_260214_Br7k5_2.hex` |
| Build date (from name) | 2025-03-25 | 2026-02-14 |
| Series | 05xx | 07xx |

Both are the 12000XP (model code `ceaa`, top-of-image `SNEC`, STM32F103 high-
density). A human-readable changelog JSON was supplied for **`ceaa-0709`**
("Based on `ceaa-0607`"), a point release just after the 07xx image here; it is
used below as a guide to *what* changed. Caveats up front:

- The binary diff is the full **05xx → 07xx** delta and therefore also spans the
  intervening **06xx** series. The `0607 → 0709` changelog covers only part of
  that span, so some deltas below (e.g. "PVChg First Stop", "Hybrid Mode") may
  have landed in 06xx and are not in the changelog.
- String extraction splits the firmware's NUL-separated text blobs. **New**
  strings are high-confidence; the **removed/renamed** set is noisier because
  the two builds pack/order their string tables differently.
- Numeric-range and control-logic changes (items 8, 10, 13, 14, 15 below) do not
  appear as strings; confirming them is a deeper disassembly follow-up.

## Headline: the 07 series moved to a bootloader + App layout

This is the biggest structural change, and it is a **direct read** of the two
vector tables (`tools/hex2bin.py` + `tools/vt.py`):

| | 05xx | 07xx |
|---|---|---|
| Vector table / VTOR | `0x08000000` | **`0x08005000`** |
| Low flash `0x08000000..0x08004FFF` | image content | **absent — reserved for a bootloader** (all `0xFF`, 20 KB) |
| Initial MSP (`vector[0]`) | `0x200008D0` | `0x2000DFD8` |
| Reset handler | `0x08002980` | `0x08030000` |
| Layout | monolithic | **App over ~20 KB bootloader** |
| Part / top marker | 512 KB, `SNEC`@`0x0807F7FC` | 512 KB, `SNEC`@`0x0807F7FC` |

The 07xx `SystemInit` writes `SCB->VTOR = 0x08005000` (the literal `0x08005000`
sits at `0x0802872C`; `SCB->VTOR` = `0xE000ED08` is referenced at `0x08038174`).
So on the 07 series the **hardware reset vector belongs to a bootloader** in the
low 20 KB, which then starts the relocated App at `0x08005000`. The 05 series
booted the application directly at the flash base.

This matches **changelog #12** — *"Multi-firmware update process now requires
only one system restart, regardless of how many updates are queued"* — i.e. a
reworked in-application-programming / bootloader path.

The reset stub itself is otherwise unchanged (same Keil-armcc idiom:
`ldr;blx`→`SystemInit`, `ldr;bx`→`__main`), confirming it is still the same
codebase and toolchain, just re-partitioned and a year of features heavier.

> **This is exactly the axis the variant descriptor already models.** The 05 vs
> 07 difference is the same `layout` / `vector_addr` / `bootloader_size` delta
> that distinguishes the 12000XP from the 18kPV (see
> [`docs/10-18kpv-vs-12000xp.md`](10-18kpv-vs-12000xp.md) and
> `include/inv/variant.h`). A 07-series 12000XP target is a variant with
> `layout = INV_IMAGE_APP_OVER_BL`, `vector_addr = 0x08005000`,
> `bootloader_size = 0x5000` — so *firmware revision*, not just *model*, is a
> dimension of that same abstraction.

## New features, seen as new HMI strings

Each row is a string that appears in 07xx and **not** in 05xx, matched to the
changelog feature it implements:

| Changelog item | New string(s) in 07xx |
|---|---|
| #1 Generator Charge Time Scheduling | `Gen Charge Time:` |
| #2 Generator Quick Start (20-min cycle) | `Gen Quick Charge Start:` |
| #3 Generator Warm-Up & Cool-Down | `Gen Cool Time:` |
| #4 Max AC Input Power Limiting | `Max Grid In Power:` |
| #6 Quick Charge Function | `Quick Charge Start:`, `System Charge SOC Limit:`, `System Charge Volt Limit:` |
| #7 Configurable Discharge Resume SOC (+5% / +2V) | `Recovery Threshold SOC:`, `Recovery Threshold Volt:` |
| #9 Battery Warning Buzzer | `Buzzer On ExCfg Enable:` |
| #11 Smart Load Power Display | `Psmart:`, `Peps_port:`, `Pgrid_side:` |

### Located: the generator-timer strings (#1/#2/#3) in the settings menu (T16, 2026-11-08)

The three generator-timer features sit together at the end of the **Generator**
settings submenu. Their label strings and the slots they occupy in the HMI
settings-menu label-pointer table (base `0x08005fec`, one 4-byte string pointer per
item) are pinned:

| # | feature | string (addr) | label-table slot |
|---|---|---|---|
| #3 | Warm-Up & Cool-Down | `Gen Cool Time: ` @ `0x0802aa60` | `0x08006154` (idx 90) |
| #1 | Charge Time Scheduling | `Gen Charge Time: ` @ `0x0802aa70` | `0x08006158` (idx 91) |
| #2 | Quick Start (20-min cycle) | `Gen Quick Charge Start: ` @ `0x0802aa84` | `0x0800615c` (idx 92) |

They follow the known gen items in the same table (idx 83-89: `Gen Charge Bat
Current`, `… Start/End SOC`, `Generator Charge Type`, `… Start/End Volt`, `Max. Gen
Input Power`, `Generator Boost Enable`). **Next step (hand-off):** the backing
settings offset / HR number for each is not yet pinned — the label table at
`0x08005fec` is reached by offset from a master menu descriptor (no direct literal or
MOVW/MOVT references it), so resolving the item→setting binding needs the HMI menu
dispatch cracked (relate to [`docs/06`](06-hmi.md) / [`docs/28`](28-factory-hmi.md)).
These are 07-new settings, so they are *not* in the published Modbus map's gen block
(HR 194-198) and likely live at fresh settings offsets past `+0xb6`.

Changelog items with **no new LCD string** (they are telemetry-export, range, or
control-logic changes — tracked here as follow-ups to confirm by disassembly):

| Changelog item | Where it lives |
|---|---|
| #5 EG4 Battery Remote BMS Update | BMS-update state already exists in the Modbus map (`IR_BMS_FW_UPD_STATE`); likely a protocol/logic extension, no new menu text found |
| #8 SOH reporting in Excel exports | `SOH:` exists in both images already; the change is on the monitoring-portal/export side |
| #10 Lead-acid absorb/float min 50 V → 48 V | a clamp constant (`500` → `480` in 0.1 V units); `Floating Voltage:` menu present in both |
| #13 3-phase overvoltage uses line-to-line (208 V) not 2× phase (240 V) | protection-threshold logic |
| #14 W04 warning not clearing on lithium→lead-acid type change | fault-state logic fix |
| #15 Generator cannot charge while Smart Load active | mode-interlock logic fix |

## Other string deltas (not in the 0607→0709 changelog)

High-confidence additions that likely arrived in 06xx:

- `PVChg First Stop SOC:` / `PVChg First Stop Volt:` — PV-charge priority stop thresholds.
- `Hybrid Mode:` — a mode setting now surfaced (05xx carried a bare `Hybrid`
  string). On a non-hybrid 12000XP this is presumably the shared-codebase option
  exposed in the menu; worth confirming whether it is selectable on this model.
- `LED Light Factor:` — reworded (05xx had a `LED Light Factor` variant with a
  different terminator), and `Parallel x`/`Parallel p` display formatting changed.

Renamed/removed (indicative only — string-table repacking makes this noisier):
`PV&AC Take Load Jointly:`, `AC First:`, `AFCT Clear:`, `FeedIN`, `N_PE_Connect`
no longer appear verbatim; several may be reworded rather than dropped. The
internal signature blob also changed (`…SNDPOTLAA1SA22` → `…SNDPOTatezLAA1SA22`).

## Image facts & integrity

| | 05xx | 07xx |
|---|---|---|
| hex md5 | `d07b6b5ddfdcddd453a3b0cc845e9659` | `ccc5172a11ea1e1b302c83bc8e834846` |
| hex size | 587,465 | 574,885 |
| flat present bytes | 244,080 | 238,856 |
| flat segments | `08000000–080029FF`, `08004E00–0803031D`, `0803151E–0803EF67`, markers | `08005000–080314FF`, `08031800–0803F7FF`, markers |

The 07 App's present byte count is slightly *lower* even though it has more
features, because ~20 KB moved out of the App into the (separate, not-included)
bootloader; the App's own code region grew (`181.5 KB` + `57 KB` vs `177 KB` +
`55 KB`).

## Method (reproducible)

```bash
python3 tools/hex2bin.py ceaa-05xx_com_vE_250325.hex   fw05.bin   # segment map
python3 tools/hex2bin.py ceaa-07xx_vE_260214_Br7k5_2.hex fw07.bin
# vectors / VTOR: tools/vt.py <bin> 0x08000000 <vt-addr>
# string diff: extract printable runs (len>=5) from each, sort -u, comm -13/-23
```

## Follow-ups

- Decode the 07 bootloader interface (where the App at `0x08005000` is entered;
  the staged-update / "one restart" queue in changelog #12).
- Locate the lead-acid min-voltage clamp (`500`→`480`) and the 3-phase OV
  threshold change to confirm #10 and #13 at the instruction level.
- Map the new menu strings to their holding registers and fold them into
  `include/inv/modbus_map.h` / the settings model.
- Obtain a 06xx image to split the 05→07 delta into 05→06 and 06→07.
