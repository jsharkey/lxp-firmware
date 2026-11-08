# 48 — Firmware updates, the SPI NOR, and the ARM's ~12 KB decode staging

**Question.** [`docs/47`](47-factory-ram-static-breakdown.md) found the single biggest
static-RAM consumer in the factory ARM image is a **~12 KB SPI-flash update/decode
staging area** (`0x20005020`–`0x20008020`). What is it — and, since that raised
several architecture questions: *does the ARM firmware live in the STM32's internal
flash or on the SPI chip? What else is on the SPI chip besides settings? Are there
several update flavours (ARM vs DSP) over the one Modbus link? Does the TI DSP load
from SPI?*

All facts below are derived by analysing `reference/ceaa-07xx_vE_260214.bin` (the ARM
**App**, `0x08005000`+) and the dongle image in the private `lxp-factory` store —
behaviour and layout, in our own words. No vendor binary/document content is reproduced.

## Where each chip's firmware actually lives

| chip | runs from | who flashes it | update transport |
|---|---|---|---|
| **ARM com-MCU** (STM32F103VE) | its **internal 512 KB flash** — bootloader `0x08000000`–`0x08005000`, **App `0x08005000`+** (App vector table proven here: SP `0x2000dfd8`, reset `0x08030001`) | the **bootloader** (after the App stages a decoded image in SPI NOR and reboots) | dongle → Modbus → SPI NOR staging → bootloader |
| **control DSP** (TI C2000) | its **own flash** | the **ARM**, over USART3, running the `0x21/0x22/0x23` "EDSN" serial loader ([`docs/05`](05-dsp-link.md), [`docs/43`](43-firmware-update-bootloader.md)) | dongle → Modbus → ARM → USART3 serial loader |
| **MPPT** | its own flash | the ARM, over USART1 ([`docs/wiring/MPPT-USART1-DSP.md`](wiring/MPPT-USART1-DSP.md)) | dongle → Modbus → ARM → USART1 |

So **the ARM firmware is in internal flash, not the SPI chip** — the SPI NOR is never
executed from; it is storage/staging. And **yes, the one Modbus link carries several
update flavours as separate operations**: an ARM-App image, a DSP image, an MPPT image.
Each peer (DSP, MPPT) programs *its own* flash from a **serial** stream the ARM drives;
**none of them loads firmware from the SPI chip.** The SPI NOR is the ARM's scratch/
staging + records store.

## What the SPI NOR actually holds (it is not "just settings")

The external **SPI NOR is large (≥ 8 MB, W25Q64-class)** and holds three different
things ([`docs/21`](21-arm-config-flash.md), [`docs/24`](24-oss-settings-region.md),
byte offsets into the chip):

| SPI NOR offset | contents |
|---|---|
| `0x000000–0x00BFFF` | **6 config slots** — the HR **settings** store (the part already known) |
| `0x040000–0x68FFFF` | **~6.5 MB journaled data-log ring** — the "offline monitoring data records" (256-B stride, double-`0xA5` marker; `HR 11` bit 4 `ResetSetting.MonitorData` clears it) |
| `0x700000 / 0x780000 …` | **firmware-update staging** — where the decode step writes (proven: the self-update orchestrator passes dst `0x700000`) |

So settings are a tiny corner of the chip; most of it is a **telemetry/event log ring**,
with a staging area at the top for updates. The STM32's *internal* flash additionally
holds a compiled-in **fallback default config record** ([`docs/21`](21-arm-config-flash.md))
and a small App-written parameter region + update marker flags (below).

## The decode/staging path (the ~12 KB) — proven

The App routine `sub_08036d68(src_spi_off, dst_spi_off)` **reads a compressed blob from
SPI NOR, LZSS-decodes it, and writes the decoded bytes back to SPI NOR** (the decoded
image lands in the staging region, e.g. `0x700000`). It works in **up to 10 chunks per
call**, each chunk:

```
 read 4-byte chunk header from SPI      -> [0:2] clen (compressed length)
                                           [2:4] dlen (decompressed length)
 if dlen == 0 or dlen == 0xffff: stop   (end-of-stream marker)
 read `clen` compressed bytes from SPI  -> 0x20005020  (the 8 KB read buffer)
 decoded = decode(0x20005020, clen,        0x20007020, cap = 0x1000)   (the 4 KB out)
 if decoded != dlen: error              (integrity check)
 program `decoded` bytes                -> SPI NOR at the running dst offset
```

So the **12 KB is a per-chunk working set, not a whole-image buffer**:

| buffer | addr | size | role |
|---|---|---|---|
| read staging | `0x20005020` | **8 KB** | one **compressed** chunk (`clen` ≤ 8 KB) |
| decode output | `0x20007020` | **4 KB** | one **decompressed** chunk (hard `0x1000` cap) |

**Codec (proven): LZSS, two variants.** `sub_08038c5c` selects a variant from the top
3 bits of the first header byte (`>>5`, `+1`): variant 1 → `sub_08038950`, variant 2 →
`sub_08038aba`. Both are **LZSS/LZ77 back-reference decoders** — a token byte whose low
5 bits (`& 0x1f`) carry a length and whose top bits select *literal* vs *match*; a match
reads a following byte to form a **13-bit back-reference** into the already-emitted
output. Consequences for sizing: the **compressed input is consumed strictly forward
(streamable)**; the **output is the match window** (matches copy from earlier in the
decoded chunk, so it must be retained up to the max back-reference distance, ≤ the 4 KB
chunk here).

### How the ARM image reaches internal flash

The App has a small **STM32 internal-flash driver** — unlock (keys `0x45670123`/
`0xCDEF89AB`), page-erase (`FLASH_CR` PER + `FLASH_AR`), halfword program
(`sub_08036c4c`), BSY-wait (`sub_08036d38`). The App uses it only for **small writes**:
a ~2 KB internal parameter region and single **update-marker flag words** (set a bit in
a status byte, program one word). The **self-update orchestrator** (`sub_0801d256`)
**decodes the received image to SPI NOR `0x700000`, validates it, sets the marker, and
reboots** (`ResetSetting.InvReboot`, [`docs/43`](43-firmware-update-bootloader.md)). The
**bulk copy of the decoded App image into internal flash `0x08005000`+ is the
bootloader's job** — the bootloader is not in this (App-only) image, so that half is
inferred from the handoff, not disassembled here.

## How the image gets to the inverter (the dongle)

The dongle is a **transparent RS-485 Modbus conduit** ([`docs/26`](26-dongle-firmware.md),
[`docs/43`](43-firmware-update-bootloader.md)): an ESP32 datalogger, **ARM = Modbus
slave**, that relays opaque register/flash frames from the cloud. Its own `spi_flash`/
OTA code is for the **ESP32's own firmware**, unrelated. Delivery is therefore **already
paced and reliable for free**: RS-485 Modbus is request/response, every frame is ACKed,
a lost/!CRC frame is **retried by the dongle**, and the ARM writes each frame to SPI NOR
as it arrives. So **receiving** an image needs only a one-frame Modbus buffer (which we
already have); the 12 KB is spent **only** on the later decode-from-SPI step.

## Can our clean-room build do it in less than 12 KB? (brainstorm)

The factory's 8 KB + 4 KB split is generous; a clean-room build has room to shrink it:

1. **Stream the compressed input → drop the 8 KB read buffer to a small window.** The
   decoder consumes compressed bytes forward-only, so pull them from SPI on demand
   behind a 256 B–1 KB ring instead of pre-reading a whole `clen` chunk. **~7 KB saved,
   no format change** — works even for EG4's official images.
2. **Page-flush the decode output as the LZSS window slides.** Once decoded output older
   than the max back-reference distance can no longer be referenced, flush it to SPI and
   reclaim it → output ≈ `max_match_distance + one page`, not the whole chunk.
3. **Cap the match window in our own update format.** If we control the packer, limit
   back-references to e.g. 1 KB → a 1 KB output window (EG4 official images keep whatever
   their packer used, ≤ 4 KB).
4. **Own uncompressed/pre-chunked format.** If interop with EG4's official images is not
   required, skip LZSS: stream small raw pages Modbus-frame → SPI/flash-page. RAM ≈ one
   256 B page. Trades wire/flash size for near-zero RAM.

**Target:** ~**1–2 KB** for a factory-image-interop build (#1 + #2), ~**256 B** for an
own raw-page path (#4).

## What our firmware needs to match factory (and what it does NOT)

- It does **not** need to run from SPI or self-program the bulk ARM image — that is the
  bootloader's job. Our ARM App, like the factory's, would **decode-stage** to SPI and
  reboot.
- To accept EG4's **official** staged update images it needs: the SPI-NOR driver
  (read / page-program / sector+block erase, confined per region — never chip-erase), the
  **two LZSS decoders**, the **chunk framer** (header, 10-chunk loop, end marker,
  `decoded==dlen` check), and the small internal-flash marker writes.
- The **data-log ring** (6.5 MB) is a separate, larger feature of its own (offline
  monitoring records) — noted here only because it shares the chip; see
  [`docs/24`](24-oss-settings-region.md) for the OSS region plan that avoids it.

## Confidence

- **Proven:** firmware runs from STM32 internal flash (App vector table here); the SPI
  NOR region map (config slots / data-log ring / staging) per docs/21/24; the chunked
  read→decode→program loop and its header fields; the two LZSS variants; the App's
  internal-flash driver and that it is used only for small writes + markers; the
  self-update orchestrator decoding to SPI `0x700000` + marker + reboot; the dongle being
  an RS-485 Modbus conduit (ARM = slave); DSP/MPPT programmed over USART3/USART1 serial
  loaders.
- **Inferred:** that the bootloader (absent from this App-only image) copies the decoded
  App image from SPI `0x700000` into internal flash; that the same decode/staging path is
  reused for the DSP/MPPT compressed images before they are streamed over USART3/USART1.
  The exact per-flavour command codes and the SPI source regions per flavour are not yet
  individually pinned.
