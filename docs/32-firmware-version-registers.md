# Firmware-version registers (HR 9 / HR 10) — one byte per processor

> **Authoritative wiring:** the version byte reaches the ARM over USART2 (safety-CPU relay) — see [`docs/wiring/ARM-USART2.md`](wiring/ARM-USART2.md). This doc remains the per-byte version-register trace.

The EG4 Modbus map exposes four firmware-version fields packed into two holding
registers. They are a clean per-processor fingerprint of the multi-CPU system, so
this note traces **where each byte actually comes from** in the factory ARM image
and standardizes the device naming the rest of the project uses.

Traced in `reference/com_flat.bin` (12000XP `ceaa-07xx`) through the holding-register
getter **`fn_ceaa` @`0x08032000`** (the serializer `sub_0803373c` calls it for the
`0x03`/holding space; the input space uses `sub_0803289c`). Register → value:

```
reg 9  (0x080323c8):  mov.w r0, #0x0500                 ; pure constant
reg 10 (0x080323ce):  ldr r0, =0x20009e54               ; the USART2 telemetry bank
                      ldrb r0, [r0, #2]                 ; low  = bank byte +2
                      adds r0, r0, #0x100               ; high = constant 0x01
```

## The four fields and their real source

| Modbus field (protocol name) | reg · byte | firmware source | describes which chip | over which link |
|---|---|---|---|---|
| **Redundant CPU** FW version | 9 · low | **constant `0x00`** | the 3rd / "safety" MCU (docs/29) | — *not populated in this image* |
| **Communication CPU** FW version | 9 · high | **constant `0x05`** | **this STM32F103 com MCU** (this project) | n/a — it *is* the ARM, baked into the build |
| **Control CPU** FW version | 10 · low | **`0x20009e56`** = USART2 bank `+2` | the **TI C2000 DSP** | **USART2** (relayed by the safety CPU) |
| **FW version code** | 10 · high | **constant `0x01`** | not a CPU — an ARM-side build/protocol code | n/a |

Byte order follows the EG4 LE convention (`reg = low | high<<8`), and the per-byte
split matches the construction above exactly.

### Standard device naming (use these consistently)

| protocol term | this project's name | chip | link to the ARM |
|---|---|---|---|
| Control CPU | **Control DSP** / "the DSP" | TI C2000 F2837x | USART3 (SCI-B, direct) + USART2 (relayed) |
| Communication CPU | **com MCU** | ST STM32F103VE | — (this project) |
| Redundant CPU | **safety CPU** | 3rd on-board MCU | USART2 (via the safety CPU link, docs/30) |

## Which version comes from the DSP we've been working on?

**The Control CPU FW version — HR 10, low byte.** It is the only one of the four read
from another processor at runtime: `fn_ceaa` reads it from `0x20009e56`, byte `+2` of
the **USART2 telemetry bank** (`0x20009e54`). That byte is written **only** by the
USART2 bulk parser `sub_080241a8` (and preserved across a comms reset by
`sub_08022c40`); there is **no USART3/DSP-direct writer** of it.

So the DSP's version reaches the ARM the same way its operating mode and PV/grid
telemetry do (docs/30): **relayed over USART2 by the safety CPU**, which sits between
the DSP (SCI-C, 9600) and the ARM (USART2, 19200 RS-485). The ARM's *direct* DSP link
(USART3/SCI-B) carries the config push + the DSP's `0x49` telemetry, but it is **not**
the source of the version register.

> The ARM side proves "reg 10 low = a byte in the USART2 frame, labelled Control-CPU
> version." That the byte is specifically the **DSP's** version (vs the safety CPU's
> own) rests on the firmware's own field label + the established relay topology; a
> DSP-side check (does the DSP emit its version in the frame the safety CPU forwards?)
> would close that last inch. The safety CPU's *own* version would be the Redundant-CPU
> field (reg 9 low), which this 12000XP image leaves at 0.

## The two constants

- **Communication CPU version = `0x05`** and **FW version code = `0x01`** are compiled
  into the ARM image (`mov #0x0500` / `adds #0x100`), i.e. this firmware reporting its
  own identity. They are build constants, not runtime-measured values, so a rebuild is
  how they change. (The values are what the 07-series App returns; they are version
  numbers in the EG4 scheme, not the `07xx` image tag.)
- **Redundant CPU version = `0x00`**: the 12000XP `ceaa` image hard-returns 0 — it does
  **not** surface a received safety-CPU version. This is consistent with docs/29's note
  that the 12000XP folds its redundancy differently from the 18kPV (whose DSP runs the
  explicit SCI-C `'T'`/`'D'` cross-check). On an 18kPV-class build this field may be
  populated; the map here is the 18kPV superset.

## Reference

| what | where |
|---|---|
| holding getter | `fn_ceaa` `0x08032000` (reg-9 case `0x080323c8`, reg-10 case `0x080323ce`) |
| input getter (other space) | `sub_0803289c` |
| serializer (calls the getter) | `sub_0803373c` (holding → `fn_ceaa`; input → `sub_0803289c`) |
| USART2 telemetry bank | `0x20009e54`; version byte at `+2` = `0x20009e56` |
| USART2 bank writer | `sub_080241a8` (bulk parser); preserved by `sub_08022c40` |
| map entries | `HR_SLAVE_COM_VER = 9`, `HR_CNTL_FW_VER = 10` (`include/inv/modbus_map.h`) |
| device roles / topology | docs/01, docs/16, docs/22, docs/29, docs/30 |
