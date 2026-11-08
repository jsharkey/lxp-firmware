# 48 — The ARM's SPI-flash decode/update staging (the ~12 KB)

**Question.** [`docs/47`](47-factory-ram-static-breakdown.md) found the single
biggest static-RAM consumer in the factory ARM image is a **~12 KB SPI-flash
update/decode staging area** (`0x20005020`–`0x20008020`). What is it, what does our
clean-room firmware need to match it, and can we do it in less RAM?

All facts below are derived by analysing `reference/ceaa-07xx_vE_260214.bin` and the
dongle image (ESP32 datalogger) in the private `lxp-factory` store — behaviour and
layout, in our own words. No vendor binary or document content is reproduced.

## What the path does (proven)

The ARM App has a routine, `sub_08036d68(src_spi_off, dst_spi_off)`, that **reads a
compressed blob from external SPI flash, LZSS-decodes it, and writes the decoded
bytes back to SPI flash** — a *decompress-to-staging* step. The external SPI flash is
reached by **bit-banged GPIO** (port block `0x40010800`, one-byte shifter
`sub_0801cb9e`), both for the read (`sub_0801cace`) and the write/program
(`sub_0801c90e → sub_0801c872`).

It processes the blob in **up to 10 chunks per call** (`cmp #0xa` loop), each chunk:

```
 read 4-byte chunk header from SPI      -> [0:2] clen (compressed length)
                                           [2:4] dlen (decompressed length)
 if dlen == 0 or dlen == 0xffff: stop   (end-of-stream marker)
 read `clen` compressed bytes from SPI  -> 0x20005020  (the 8 KB read buffer)
 decoded = decode(0x20005020, clen,        0x20007020, cap = 0x1000)   (the 4 KB out)
 if decoded != dlen: error              (integrity check)
 program `decoded` bytes                -> SPI flash at the running dst offset
```

So the **12 KB is a per-chunk working set, not a whole-image buffer**:

| buffer | addr | size | role |
|---|---|---|---|
| read staging | `0x20005020` | **8 KB** | one **compressed** chunk (`clen` ≤ 8 KB) |
| decode output | `0x20007020` | **4 KB** | one **decompressed** chunk (hard `0x1000` cap) |

### The codec (proven): LZSS, two variants

The decoder `sub_08038c5c` selects a variant from the **top 3 bits of the first
header byte** (`>>5`, `+1`): variant 1 → `sub_08038950`, variant 2 → `sub_08038aba`.
Both are **LZSS/LZ77 back-reference decoders**: a token byte whose low 5 bits
(`& 0x1f`) carry a run length and whose top bits select *literal* vs *match*; a match
reads a following byte to form a **13-bit back-reference** (`(tok<<8 & 0x1f00) | next`,
distance up to `0x1fff`) that copies already-emitted output. Consequences for sizing:

- the **compressed input is consumed strictly forward** (`ldrb [p]; p++`) — it is
  **streamable**;
- the **output is the match window** — a match copies from earlier in the *decoded*
  chunk, so the decoder must retain the decompressed bytes it has emitted, up to the
  largest back-reference distance used (bounded by the chunk size, ≤ 4 KB here).

## How the image gets there (the dongle side)

The dongle is a **transparent RS-485 conduit**, not a flasher ([`docs/26`](26-dongle-firmware.md),
[`docs/43`](43-firmware-update-bootloader.md)): an ESP32 datalogger whose inverter
link is RS-485 running the EG4-Modbus protocol with the **ARM as the slave**
(`RS485App.c` / `rs485_service_task` in the dongle image; its own `spi_flash`/OTA code
is for the ESP32's *own* firmware). It relays opaque register/flash frames from the
cloud to the ARM; the ARM is the only thing that writes any inverter flash.

**Delivery is therefore already paced and reliable, for free:**

- RS-485 Modbus is **request/response with the ARM as slave** — every frame the
  dongle sends is acknowledged by the ARM, and a lost/!CRC frame is **retried by the
  dongle** (standard Modbus master retry). There is no push-faster-than-acked path.
- The dongle streams the update **frame by frame**; the ARM writes each frame to SPI
  flash as it arrives. So **receiving** the image needs only a one-frame Modbus buffer
  (which our firmware already has), **not** a whole-image RAM buffer.
- The 12 KB staging is spent **only on the later decode-from-SPI step**, which runs
  from SPI at its own pace, independent of the wire.

Net: our implementation can **rely on paced, ACKed, dongle-retried delivery** and does
not need large receive buffers; the RAM question is purely about the *decode* step.

## What our firmware needs to match factory

We do not implement any of this today (our `.bss` is ~4 KB; [`docs/45`](45-arm-ram-budget.md)).
To accept the **same** staged, compressed update images the factory + dongle + cloud
already produce, a clean-room implementation needs:

1. a **bit-banged SPI-flash driver** (read + page-program + sector-erase) for the
   external chip;
2. the **two LZSS decode variants** (format selected by the header byte's top 3 bits);
3. the **chunk framer** (4-byte `clen`/`dlen` header, 10-chunk loop, `dlen==0/0xffff`
   end marker, `decoded==dlen` integrity check);
4. the **staging buffers** and the SPI read/program plumbing.

## Can we use less than 12 KB? (brainstorm)

The factory's 8 KB + 4 KB split is generous; several reductions are open to a
clean-room build. In rough order of safety/size:

1. **Stream the compressed input → drop the 8 KB read buffer to a small window.**
   The decoder consumes compressed bytes forward-only, so instead of pre-reading a
   whole `clen` chunk into 8 KB, pull compressed bytes from SPI on demand behind a
   small ring (e.g. 256 B – 1 KB). **Saves ~7 KB with no format change** — works even
   for EG4's official images. (SPI reads get more numerous but each is tiny.)
2. **Cap the match window in our own update format → shrink the 4 KB output.** The
   4 KB output exists because an LZSS match may reference up to a chunk back. If we
   control the producer (our own packer/dongle path), limit back-references to e.g.
   1 KB and chunk to 1 KB → a **1 KB output window**. For EG4 official images the
   window is whatever their packer used (≤ 4 KB), so this only helps our own images.
3. **Program per flash page as the window slides.** Flash programs in 256 B pages;
   once decoded output older than the max match distance can no longer be referenced,
   flush it to flash and reclaim it. Turns the output buffer into `max_match_distance +
   one page`, not the whole chunk — again only as small as the format's match window
   allows.
4. **Accept an uncompressed / pre-chunked format of our own.** If interop with EG4's
   official update images is *not* required (our own update tool), skip LZSS entirely
   and stream small raw pages straight from Modbus frame → SPI/flash page → done. RAM
   cost ≈ one page (256 B). Trades wire/flash size for near-zero RAM.
5. **Overlap the two buffers.** With streaming input (#1) the compressed window and the
   decode output never need their full sizes simultaneously; a single arena sized to
   `max(small_input_window, output_window)` suffices.

**Recommendation.** For *interop* with factory images: do #1 (stream input) + #3
(page-flush output) → from 12 KB down to roughly **1–2 KB**. For an *own* update path:
do #4 → ~256 B. Decide interop-vs-own before building, because it sets the window
sizes and whether LZSS is needed at all.

## Confidence

- **Proven:** the chunked read→decode→program loop, the chunk header fields, the LZSS
  back-reference decode and its two variants, the bit-banged SPI target, the per-chunk
  buffer sizes, and that the dongle is an RS-485 Modbus conduit (ARM = slave).
- **Inferred:** that the decoded output staged back in SPI flash is a firmware image a
  later bootloader programs (vs a data-log decode) — [`docs/47`](47-factory-ram-static-breakdown.md)
  labels it the firmware-update/data-log path; the decode mechanism and the buffer
  budget are the same either way. The exact trigger (`sub_08036d68` is dispatched
  indirectly, not via a direct `BL`) and the SPI region map are not yet pinned.
