# Frame header (`0x00`–`0x14`) — the 20-byte type-1 envelope

> **ARM↔DSP link**, type-1 block protocol. Precedes the payload of **every** config
> block and the telemetry frame. See the [index](README.md).

Every type-1 frame is a fixed 20-byte header, then the block id, then the payload,
then a CRC-16 trailer:

```
off 0x00  SOF    : 0x41 ('A')  ARM→DSP config   |   0x49 ('I')  DSP→ARM telemetry
off 0x01  type   : 0x01
off 0x02  0x00
off 0x03  len    : 0x36 (54)              frame-length discriminator for this family
off 0x04 .. 0x13 fixed header (18 bytes): a 32-bit id/serial @ 0x05 (BE), plus
                 status/flags; three fields the DSP pulls out —
                   [0x05] → DSP 0xAD60,  [0x0D] → DSP 0xAD82,  [0x13] → DSP 0xAD5F
                 (exact subfields — serial vs pushed timestamp — not fully mapped)
off 0x14  block id : 0..8 (config) — selects the payload layout (see per-block docs)
off 0x15  payload  : big-endian, per-block
off  …    CRC-16/MODBUS (0xA001, init 0xFFFF) over the frame
```

## Facts

- **The discriminator is the block id at `0x14`, not a byte count.** The DSP tests
  `buf[0x14]` only in a 9-way `== 0 … == 8` switch; it never uses it as a
  length/address. This is what makes the frame *block-tagged*, not Modbus
  `addr/func/SN/start/count`.
- **No serial-number field.** The receive path does no `SN[10]` check; the header
  is 18 bytes of id/serial/status that are the **same for every block**.
- **SOF asymmetry.** ARM→DSP uses `0x41`; DSP→ARM telemetry uses `0x49`. The DSP RX
  (`FUN_00098F72`) checks `buf[1]==1` (type), not the SOF; the ARM RX
  (`FUN_0801bb0e`) keys on `0x49`.
- **CRC** is CRC-16/MODBUS; the DSP's `FUN_00081034` is the mechanical twin of the
  ARM's `sub_08000d98`.

## Reader primitives (DSP side)

| reader | returns | wire width |
|---|---|---|
| `FUN_0009E7C2(p)` | `(p[0]<<8) \| p[1]` → **u16 BE** | 2 |
| `FUN_0009E6BA(p)` | **u32 BE** (`p[0]`..`p[3]`, MSB first) | 4 |
| direct word read | **u8** (one wire byte) | 1 |

ARM builder: `FUN_080273b4` (writes the header, rotates the block id) → `FUN_08026830`
(`buf[0x14]=blockId`, BE values from `buf[0x15]`). Reimplementation:
[`src/dsp/dsp_config.c`](../../src/dsp/dsp_config.c).

## Open

- The 18-byte header subfields at `0x04..0x13` (serial-number vs pushed-timestamp
  split) are not decoded; `[0x05]`/`[0x0D]`/`[0x13]` are the only three the DSP
  extracts (→ `0xAD60`/`0xAD82`/`0xAD5F`).
