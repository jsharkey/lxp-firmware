# A forward-compatible OSS settings region on the config flash

> **Authoritative wiring:** the SPI1↔config-flash link is distilled in [`docs/wiring/ARM-SPI1.md`](wiring/ARM-SPI1.md). This doc remains the OSS forward-compat region plan.

We want the open reimplementation to persist **new** settings of its own on the
same SPI NOR config flash, while keeping the factory's settings
([`docs/21`](21-arm-config-flash.md) / [`docs/23`](23-arm-config-writer.md)) intact
and byte-identical. The hard requirement: **if a unit is flashed back to the
factory firmware, the factory must ignore our new settings** — never read them as
config, never wedge boot, never be "corrupted" by them.

This note records where it is safe to do that, and the record format that makes the
factory skip our data as unrecognized.

All addresses are SPI-NOR byte offsets (not MCU flash). Findings are from the
`ceaa-07xx` 12000XP "com" image, same as docs/21/23.

## The factory's real flash map is bigger than the config store

docs/21 characterized the six 8 KB config slots at `0x000000–0x00BFFF`. But the
factory uses far more of the chip. Every caller of the SPI erase primitive
`sub_0801c7b2(mode, addr)` was traced; `mode` selects the opcode:

| mode | opcode | span |
|---|---|---|
| 0 | `0x20` | 4 KB sector |
| 1 | `0x52` | 32 KB block |
| 2 | `0xD8` | 64 KB block |
| 3 | `0xC7` | **chip erase** |

The regions in use:

| Flash region | Purpose | Erase seen |
|---|---|---|
| `0x000000–0x00BFFF` | **6 config slots** (settings) — fixed by the 6-entry descriptor table @`0x080057b8` | 4 KB sector (`sub_080164bc`, `sub_08016652`) |
| `0x040000–0x68FFFF` | **~6.5 MB journaled data-log ring** — double-`0xA5` marker, 256-B stride (almost certainly the "offline monitoring data records"; HR 11 bit 4 `ResetSetting.MonitorData` clears it) | 4 KB + 64 KB block (`sub_08037920/a9e`, `sub_080378f0`) |
| `0x700000 / 0x780000 …` | further store/staging (`fn_NOTB` → `sub_08036f78/fe2`) | 64 KB block |

Two facts make a safe hole possible:

- **No caller passes `mode 3` (chip erase) or `mode 1` (32 KB).** Only 4 KB-sector
  and 64 KB-block erases, each confined to its own region. Nothing wipes the chip.
- **The config writer only 4 KB-sector-erases within `0x0000–0xBFFF`** — it never
  64 KB-block-erases, so it never even touches the rest of block 0 (`0xC000–0xFFFF`).

The chip is large: the factory addresses `0x780000+`, so these units carry **≥ 8 MB**
of SPI NOR (e.g. W25Q64). The config store is firmly **six** slots — descriptor
table entry 6 is unrelated data, so config never extends past `0x00BFFF`.

## The chosen region: `0x010000–0x03FFFF`

Put the OSS settings in the gap **between** the config block and the log ring, on a
64 KB-block boundary:

```
0x000000  ┌─────────────────────────┐  block 0
          │ factory config slots 0–5│  (0x0000–0xBFFF, 4 KB-erased only)
0x00C000  │  …unused tail of block 0│
0x010000  ├─────────────────────────┤  blocks 1–3  ← OSS SETTINGS REGION (192 KB)
          │   open-source settings  │
0x040000  ├─────────────────────────┤
          │  factory data-log ring  │  (…0x68FFFF)
          └─────────────────────────┘
```

Why this region:

- It is a **separate 64 KB block from the config** (config is block 0, `0x0000–
  0xFFFF`), so even a 64 KB-block erase of the OSS region can never clip factory
  config.
- It is **below the log ring's floor** (`0x040000`), whose lowest erase is the 64 KB
  block at `0x40000` — that can't reach down into the OSS region.
- It is bounded by the **two best-decoded** factory regions, so "is this really
  unused?" rests on evidence rather than a guess about the `0x700000` area.

192 KB is far more than needed; a single 64 KB block (`0x010000–0x01FFFF`) is plenty
if you prefer to leave `0x020000–0x03FFFF` as further headroom.

## Record format — reuse the geometry, change the identity

Reuse the factory's proven 256-byte page + CRC-16/MODBUS scheme (so the loader,
writer, CRC and journaled-ring wear-levelling code can be shared), but make each
record **self-identifying and factory-rejectable**:

```
offset  size  field
0x00      4   magic  "LXP1" (0x4C 0x58 0x50 0x31)   — signature + format id
0x04    246   OSS settings payload
0xFA      2   CRC-16/MODBUS of [0x00:0xFA], little-endian   (identical to factory)
0xFC      2   reserved (0xFF)
0xFE      1   layout/version
0xFF      1   marker = 0x5A   — deliberately NOT 0xA5
```

Organize the region as a journaled ring exactly like a factory slot (append the new
record to the next free page; newest valid record wins on readback; 4 KB-sector
erase on wrap) — it is the same power-fail-safe, wear-levelling design, and gives
the same ~32 × endurance records per 8 KB of ring (see docs/21's lifetime note).

## Why the factory ignores it — two independent layers

1. **It is never addressed.** The config loader (`sub_0801683C`) reads only the six
   slots named in the descriptor table (`0x0000–0xBFFF`); the log ring reads only
   `≥0x40000`. Nothing in the factory scans `0x010000–0x03FFFF`. This is the real
   guarantee: the factory cannot be confused by bytes it never reads.
2. **Even if a future factory build scanned it, it rejects the records.** The config
   validator `sub_08016652` accepts a record only if `byte[0xFF] == 0xA5` **and** the
   payload CRC matches. Our marker is `0x5A`, so the record is skipped as "not
   written / invalid" — precisely the corrupted/unrecognized → skip behavior we
   want. The data-log validator wants `0xA5,0xA5` at `[0,1]`; our magic begins with
   `'L'` (`0x4C`), so it is rejected there too. A freshly-erased region is `0xFF` at
   `[0xFF]`, also skipped.

The magic at `[0x00]` does the mirror job: it stops **our** firmware from mistaking
an erased page, factory garbage, or a half-written record for a valid OSS record.

Net effect of a flash-back-to-factory: the factory boots normally off the untouched
slots 0–5 (which we keep byte-identical in factory format), and the OSS region lies
dormant and invisible.

## Caveats / verify before freezing the layout

- **Size the chip at runtime.** The driver already issues JEDEC `0x9F`
  (`sub_0801cb4e`, site `0x0801cb68`); read the capacity byte and refuse the OSS
  region if the chip is smaller than assumed. A smaller part would alias the OSS
  region onto a real one through address wrap.
- **Do not co-locate inside a factory slot ring.** A `0x5A`-marked record appended
  into slots 0–5 would be skipped on read, but it desyncs the factory's per-slot
  ring write-pointer and could be erased by the factory's wear-levelling. Keep the
  OSS store in its own region.
- **Prove the gap is clean on real hardware.** On a factory-fresh unit, dump
  `0x010000–0x03FFFF` and confirm all `0xFF`; then exercise every factory feature
  that writes flash — change settings, trip and clear a fault (HR 11 bit 3), let it
  accumulate monitoring data (bit 4), run `AlltoDefault` (bit 1) — and re-dump to
  confirm the region is still untouched. This closes the "is there a store I didn't
  find statically?" gap.
- **Keep the factory region authoritative for shared settings.** Read/write slots
  0–5 in factory format for anything both firmwares understand (the register→offset
  map in docs/23), and use the OSS region only for genuinely new settings — otherwise
  a round-trip through factory silently reverts them.

## Open questions

- Exact extent/purpose of the `0x700000`/`0x780000` region(s) (`fn_NOTB`) and whether
  any factory path issues a chip-erase outside the config/log/`fn_NOTB` code traced
  here (e.g. a manufacturing or firmware-update routine).
- The data-log ring's record layout (`0x040000–0x68FFFF`) is only identified by its
  double-`0xA5` marker and stride, not decoded.
