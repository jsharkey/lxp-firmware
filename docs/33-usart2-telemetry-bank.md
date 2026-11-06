# The USART2 telemetry bank (`0x20009e54`) — format and dongle exposure

> **Dongle registers:** this bank→register map is the **provenance source** that the dongle per-register docs cite for input-register origins. Dongle-facing register docs: [`docs/modbus-dongle/`](modbus-dongle/README.md).

> **Authoritative wiring:** the USART2↔safety-CPU link itself (pins, electrical,
> direction) is in [`docs/wiring/ARM-USART2.md`](wiring/ARM-USART2.md), which
> cites this doc for the bank field map. This doc is the authoritative **bank
> format + dongle-register** reference.

The ARM's richest single telemetry structure is the **USART2 bank at `0x20009e54`**.
It holds the operating mode, the grid/PV measurements, and the fault/warn status the
**safety CPU sends to the ARM over USART2** (docs/30). Per the DSP-side follow-up
(docs/29), the measured quantities are the **safety CPU's own independent samples** —
the DSP forwards it no grid/PV; the **only** DSP-originated field is the operating-mode
byte (`BANK+0`), which the DSP hands the safety CPU on SCI-C to relay. This note
documents (1) how
the bank is filled from the wire frame, (2) its field map, and (3) **which fields reach
the external Modbus dongle** as input/holding registers.

Everything here is from the factory ARM image `reference/ceaa-07xx_vE_260214.bin` (12000XP
`ceaa-07xx`): the parsers `sub_080259d8` / `sub_08024d74` / `sub_080241a8` (write side)
and a sweep of the register getters `sub_0803289c` (input) / `fn_ceaa` (holding) over
every register, recording which bank offset each reads (read side).

## 1. How the bank is filled

The USART2 peer sends an **EG4 "type-1", big-endian, CRC-16/MODBUS** frame (the DSP
family, docs/10). The receive pipeline:

```
USART2 RX  →  staging 0x20008084  →  sub_080259d8 (driver/validate)
                                        • CRC-16 check (sub_08014bec)
                                        • gate: frame[1] == 1 (type) and length ≥ 0x54
                                        • maintains link health in 0x2000a6c4 + fail
                                          counters 0x20009048[6]  (→ comms-loss / E017)
                                        ↓ on a good frame
                                     sub_08024d74 (header)   writes fixed offsets:
                                        frame[+4]  → BANK+0x00   operating mode (u8)
                                        frame[+5]  → BANK+0xd0   FAULT status (BE u32)
                                        frame[+9]  → BANK+0xd4   WARN  status (BE u32)
                                        frame[+0d] → BANK+0x01   mode-2 byte (u8)
                                        frame[+0f] → BANK+0xc4   (BE u16)
                                        frame[+11] → BANK+0xca   (u8)
                                        ↓ then
                                     sub_080241a8 (bulk, from frame[+0x14])
                                        tag-keyed sub-records (tag byte selects a block;
                                        each block is a run of big-endian u16/u32/bytes
                                        copied into fixed bank offsets)
```

All multi-byte reads are **big-endian**: `sub_08014db8` (u16 = `p[0]<<8|p[1]`),
`sub_08014dd4` (u32 = `p[0]<<24|…|p[3]`). This is the discriminator vs the dongle's
little-endian framing (docs/08/26). On an invalid/short frame the driver zeroes
`BANK+0`, `BANK+0xd0`, `BANK+0xd4` so stale mode/faults don't persist.

The bank is a **parsed structure, not a raw frame copy** — fields land at fixed bank
offsets regardless of their position in the wire frame, so the bank offset (not the
frame offset) is the stable identifier used everywhere else.

## 2. Bank field map

Width/endianness are from the parser; "dongle register" is from the getter sweep
(the register the dongle can poll that returns this field). `s16` where the register
is signed.

### Mode / identity / status (header + tag-0)

| bank off | width | dongle reg | field |
|---|---|---|---|
| `+0x00` | u8 | IR 0 `STATE` *(via classifier)* | **operating mode** (frame `+4`) — the **one DSP-originated field** (`DAT_0001230E`, relayed by the safety CPU; docs/29); canonicalized into `IR_STATE` by `sub_0801b480` |
| `+0x01` | u8 | *(classifier input)* | secondary mode/status byte (frame `+0d`) |
| `+0x02` | u8 | **HR 10 low** | **Control-CPU (DSP) FW version** (docs/32) |
| `+0x03..+0x06`, `+0x08` | u8 | — | peer identity/version bytes — preserved across a comms reset by `sub_08022c40` |
| `+0xd0` | BE u32 | **IR 60/61 `FAULTCODE`** *(via `STATUS+0x88`)* | **fault bitfield** (frame `+5`). Copied verbatim except bits 0 (E000) & 17 (E017) which the ARM sets locally. **E027 (bit 27) is the frame's own bit.** |
| `+0xd4` | BE u32 | **IR 62/63 `WARNCODE`** *(via `STATUS+0x8c`)* | **warn bitfield** (frame `+9`): bits 10–31 (grid warns `W016/17/18`, …) from the frame; bits 0–9 (incl. `W008`) are ARM-computed locally |

> The two status words do not become registers directly: the classifier `sub_0801b480`
> merges each with the ARM-local fault/warn accumulator `0x2000a6c4(+4)` into
> `STATUS 0x2000a0d8 +0x88`/`+0x8c`, which the getter then serves as IR 60–63. See
> docs/30 for why this makes USART2's peer the safety CPU.

### Measurements exposed to the dongle (confirmed bank → input register)

All of these are the **safety CPU's own measurements** (docs/29): the DSP does not feed
grid/PV to the safety CPU, so the ARM publishes the sampler's numbers.

| bank off | width | dongle reg | quantity (unit) |
|---|---|---|---|
| `+0x0a` | BE u16 | IR 107 | inverter-side battery voltage (0.1 V) |
| `+0x0c` | BE u16 | IR 105 | (mapped to `IR_BMS_FW_UPD_STATE` slot) |
| `+0x0e` | BE u16 | IR 38 | BUS 1 voltage (0.1 V) |
| `+0x10` | BE u16 | IR 39 | BUS 2 voltage (0.1 V) |
| `+0x12` | BE u16 | IR 120 | half-BUS voltage (0.1 V) |
| `+0x1c` | BE u16 (s16) | IR 66 | radiator temperature 2 (°C) |
| `+0x1e` | BE u16 (s16) | IR 65 | radiator temperature 1 (°C) |
| `+0x20` | BE u16 | IR 12 | grid voltage R / L1 (0.1 V) |
| `+0x22` | BE u16 | IR 20 | EPS output voltage R / L1 (0.1 V) |
| `+0x24` | BE u16 | IR 18 | inverter current RMS (0.01 A) |
| `+0x28` | BE u16 | IR 13, IR 121 | grid voltage S / L2 (also read for generator voltage) (0.1 V) |
| `+0x30` | BE u16 | IR 127 | EPS voltage L1-N (0.1 V) |
| `+0x32` | BE u16 | IR 128 | EPS voltage L2-N (0.1 V) |
| `+0x4c` | BE u16 | IR 1 | **PV1 voltage** (0.1 V) |
| `+0x4e` | BE u16 | IR 2 | **PV2 voltage** (0.1 V) |
| `+0x5e` | BE u16 | IR 15 | **grid frequency** (0.01 Hz) |
| `+0x60` | BE u16 | IR 23 | EPS output frequency (0.01 Hz) |
| `+0x62` | BE u16 | IR 122 | generator frequency (0.01 Hz) |
| `+0xaa` | BE u16 | IR 19 | power factor (0.001) |
| `+0xb6` | BE u16 | IR 14 | grid voltage T (0.1 V) |
| `+0xb8` | BE u32 | IR 92/93 | *(32-bit; project map labels IR 90–94 BMS — see caveat)* |
| `+0xbc` | BE u32 | IR 90/91 | *(32-bit; see caveat)* |
| `+0xc4` | BE u16 | IR 94 | (frame `+0f`) |
| `+0xc8` | BE u16 | IR 6 | internal fault/DTC (combined with `STATUS+0x91`) |
| `+0xd8`,`+0xdb` | u8 | IR 21 | EPS voltage S / L2 (two bytes combined) |

### Parsed but not mapped to a register in this image

The bulk parser fills a dense measurement block whose offsets are **not read by any
register getter** in the 12000XP `ceaa` image (confirmed by the full sweep):
`+0x13`, `+0x14`, `+0x16`, `+0x18` (u32), `+0x26`, `+0x2a`, `+0x2c…+0x3e`,
`+0x40…+0x52`, `+0x64…+0xa8` (a run of BE u32 + u16), `+0xb0`, `+0xb4`, `+0xc0` (u32),
`+0xca`. The parser also writes an **extended region past `+0x100`** (e.g. `+0x258`,
`+0x25c/+0x25d`, into `0x2000a0ac+`). These are most likely (a) raw inputs to
ARM-computed/accumulated registers served from other structs (energy totals in
`0x20009954`, powers computed by `sub_0801a678`/`sub_0801b034`, docs/22), or (b)
superset/variant fields not surfaced on this 2-MPPT build. They are received telemetry
but do **not** reach the dongle verbatim.

## 3. What actually reaches the Modbus dongle

The external datalogger **"dongle" on UART5** polls the ARM as a Modbus master, reading
input registers (func `0x04`) and holding registers (`0x03`). The **same getters**
(`sub_0803289c` / `fn_ceaa`) serve the dongle, the HMI and the DSP-config path, so every
register in the map above is dongle-reachable. From the USART2 bank, the dongle sees:

- **Operating state** — IR 0 (classified from `BANK+0`).
- **PV** — PV1/PV2 voltage (IR 1/2). *(PV **power** IR 7/8 is ARM-computed from these,
  not a bank field; docs/22.)*
- **Grid** — voltage R/S/T (IR 12/13/14), frequency (IR 15), power factor (IR 19),
  inverter current (IR 18).
- **EPS / backup** — voltage R/S (IR 20/21), L1-N/L2-N (IR 127/128), frequency (IR 23).
- **BUS** — BUS1/BUS2 (IR 38/39), half-BUS (IR 120).
- **Generator** — voltage (IR 121), frequency (IR 122).
- **Temps** — radiator 1/2 (IR 65/66).
- **Faults/warnings** — IR 60/61 (fault, incl. E027) and IR 62/63 (warn, grid warns);
  internal-fault DTC IR 6.
- **Versions** — Control-CPU/DSP FW version in HR 10 low (`BANK+2`, docs/32).

Everything else the dongle reads — daily/total **energy** counters, battery pack data
(**BMS over CAN1**, docs/20), computed **powers**, settings in the holding space — comes
from **other** sources, not this bank. So the USART2 bank is specifically the **safety
CPU's instantaneous grid/PV-measurement + fault channel, plus the one DSP-originated
operating-mode byte**; the dongle re-exports its instantaneous electrical quantities and
the operating/fault state, while energy totals and battery data are merged in from
elsewhere.

## Caveats

- **Image-specific.** Offsets and the register mapping are the 12000XP `ceaa` factory
  getter. The `modbus_map.h` register *meanings* are the 18kPV superset; where the
  factory getter and the superset label disagree (notably **IR 90–94**, which the map
  calls BMS-status but the factory serves from `BANK+0xb8/0xbc`), the table marks it —
  worth a dedicated check before relying on those slots.
- **Not a frame dump.** The field map is bank offsets; exact wire-frame offsets exist
  only inside the tag sub-records (sequential within each tag) and aren't needed to use
  the bank.
- Two registers abort the emulated getter on unrelated paths (`pc 0x08032eda`,
  `0x08032524`); neither is a bank-fed register, so the map above is complete for the
  bank.
