# ARM config storage — the SPI NOR settings flash (journaled, 6 slots)

> **Authoritative wiring:** the SPI1↔config-flash link is distilled in [`docs/wiring/ARM-SPI1-flash.md`](wiring/ARM-SPI1-flash.md). This doc remains the read-side detail.

[`docs/09`](09-dsp-persistence-and-clock.md) established that the **ARM owns
persistence** — the DSP keeps nothing across a power cycle and is re-seeded by
the ARM every boot. This note answers the follow-up: *where and how* does the ARM
store its settings? The answer is an **external SPI NOR flash** holding a
**journaled, wear-levelled config store of six 8 KB slots**, which the firmware
loads during early init and cannot finish booting without.

Findings are from the `ceaa-07xx` 12000XP "com" image. Addresses are in that
image's App space (vectors @`0x08005000`).

## How this was found

Not by static RE alone — by **running the factory image** in the `arm_sim`
emulator ([`docs/19`](19-gpio-test-harness.md)) with a modelled SPI NOR flash
(`SpiNorFlash` / `attach_spi_flash()`) and watching where boot got stuck.

1. **Boot hangs re-reading SPI.** With a blank (all-`0xFF`) flash attached, boot
   never reaches task creation; it loops issuing SPI reads. Instrumenting the
   reads showed 256-byte pages being read **descending** from the top of a
   region (`0x1F00, 0x1E00, … 0x0000`), then the next region (`0x3F00 … 0x2000`),
   and so on — a classic journaled store being scanned newest-first.
2. **The stuck call chain** is `sub_0802E4DC` (the first init step of the task
   setup `sub_0802E2F0`) → its last child `sub_08014696` → `sub_0801683C`, the
   **config loader**. It is reached *before* task registration, so until it
   returns the firmware never creates its tasks or starts the scheduler — this is
   why a blank chip wedges the whole boot.
3. **The record validator** is the per-page scan `sub_08016652`. Disassembling it
   gave the record format (below): a `0xA5` marker byte and a 16-bit checksum.
4. **The checksum is Modbus CRC-16.** The check calls `sub_080160BC`, a
   table-driven CRC over two 256-byte tables (at `0x0802EA58` and `0x0802EB58`).
   Extracting the tables and running the routine against random inputs matched a
   textbook CRC-16/MODBUS (init `0xFFFF`, poly `0xA001`) exactly — the same CRC
   the repo already uses for the wire protocol (`inv_modbus_crc16`, `src/modbus`).
5. **Confirmed by provisioning it.** Writing one valid record (marker + correct
   CRC) at the top page of each slot makes all six slots validate on the first
   read, config load completes, and boot proceeds all the way into the scheduler.
   That is exactly what `ArmSim.attach_config_flash()` does.

## Physical layer

A standard SPI NOR part on **SPI1**, chip-selected by **PA4** (active low). The
driver speaks the usual command set — JEDEC id (`0x9F`), read (`0x03`), page
program (`0x02`), WREN (`0x06`), RDSR (`0x05`), sector/block erase
(`0x20/0x52/0xD8`) — through a one-byte SPI primitive and a multi-byte read:

| Function | Role |
|---|---|
| `sub_0801CB9E` | `spi_byte(tx) -> rx`: wait `SR.TXE`, write `DR`, wait `SR.RXNE`, read `DR` |
| `sub_0801CB02` | read *N* bytes: send `0x03` + 24-bit address, then clock out *N* bytes |
| `sub_0801CACE` | wrapper: assert CS, read a page into a RAM buffer, deassert CS |

## Record format (256 bytes = one flash page)

Each record occupies one 256-byte page:

```
offset  size  field
0x00    250   payload (the settings bytes for this slot)
0xFA      2   CRC-16/MODBUS of payload[0x00..0xFA], little-endian
0xFC      3   unused
0xFF      1   0xA5  "record written" marker
```

A record is **valid** iff `byte[0xFF] == 0xA5` **and**
`u16le(byte[0xFA:0xFC]) == crc16_modbus(byte[0x00:0xFA])`. (Validator:
`sub_08016652` → `ldrb [buf,#0xFF]; cmp #0xA5` then the CRC compare via
`sub_080160BC`.)

## Store layout — six slots, journaled

The flash is divided into **six slots** (config "types" 0–5), each an **8 KB
region**:

| Slot | Flash region | Records |
|---|---|---|
| 0 | `0x000000 – 0x001FFF` | 32 × 256 B |
| 1 | `0x002000 – 0x003FFF` | 32 × 256 B |
| 2 | `0x004000 – 0x005FFF` | 32 × 256 B |
| 3 | `0x006000 – 0x007FFF` | 32 × 256 B |
| 4 | `0x008000 – 0x009FFF` | 32 × 256 B |
| 5 | `0x00A000 – 0x00BFFF` | 32 × 256 B |

Slot *N* starts at `N * 0x2000`. Within a slot the 32 record pages form a
**ring**: a setting change is appended to the next free page rather than
rewritten in place (flash wear-levelling / power-fail safety). The loader
(`sub_0801683C`) walks each slot from its **top page downward** and takes the
**first valid record** it finds — i.e. the newest write wins. It retries a slot a
few times before giving up on it.

## Fallback defaults in internal flash

If a slot has no valid record on the SPI chip, slots **0 and 5** fall back to a
**compiled-in default record in the MCU's own internal flash**, via
`sub_0801D144`:

| Slot | Default record address (internal flash) |
|---|---|
| 0 | `0x0807F800` |
| 5 | `0x0807F900` |

These defaults use the same 256-byte record format (marker + CRC). Notably, in
the `ceaa-07xx` image **these addresses are past the end of the dump** — the
image ends exactly at `0x0807F800` — so the default pages are *not present* in
the file we have (they are either programmed separately at manufacturing or live
in a flash region the dump omits).

## Consequence for emulation / bring-up

Because config load sits in the boot path before task creation, and because a
blank SPI chip plus absent internal defaults leaves **no** valid record for any
slot, the stock image **cannot boot** against an empty flash — it loops in
`sub_0801683C` forever. A faithful emulation (or a bench board with a blank chip)
must present valid config the way a factory-programmed unit does.
`attach_config_flash()` does this: it writes one valid, CRC'd record at the top
page of each slot, after which boot runs config → task creation → scheduler end
to end. See [`docs/19`](19-gpio-test-harness.md).

## Open questions

- **Payload layouts.** Each slot's 250-byte payload is a distinct settings
  structure; the field maps per slot are not yet reversed. (A blank-but-valid
  record — zero payload, correct CRC — is enough to clear the boot gate, which is
  all the emulator needs today.)
- **What selects which slot** for a given setting, and how the ring's write
  pointer is tracked, is only partly mapped (the loader side is understood; the
  writer side is not).
- The **internal-flash default records** (`0x0807F800/0x0807F900`) could not be
  inspected in the `ceaa-07xx` dump; a complete dump would show the real default
  payloads for slots 0 and 5.
