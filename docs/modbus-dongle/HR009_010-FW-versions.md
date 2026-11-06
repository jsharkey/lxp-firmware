# HR 9-10 — firmware versions (per processor)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg·byte | field | processor | value in ceaa-07xx |
|---|---|---|---|
| 9 low | Slave/Redundant CPU ver | safety CPU | const `0x00` (not populated on 12000XP) |
| 9 high | Communication CPU ver | **this STM32 ARM** | const (ARM's baked-in build ver) |
| 10 low | Control CPU ver | TI C2000 **DSP** | from USART2 bank `BANK+2` (`0x20009e56`) |
| 10 high | FW version code | — (ARM build code) | const |

## Where the data comes from

These live in the *holding* space but are effectively **read-back status**, each a
FW version byte. Traced in the factory image via the holding getter `fn_ceaa`
([`docs/32`](../32-firmware-version-registers.md)):

- The **only** version read from another processor at runtime is the **Control CPU
  (DSP) version, HR 10 low** — it comes from the **USART2 bank byte +2**, written
  by the USART2 parser `sub_080241a8`. So the DSP's version reaches the dongle the
  same relayed way as its mode/telemetry: **over USART2 via the safety CPU**, not
  on the direct USART3/DSP link. See [`docs/wiring/ARM-USART2`](../wiring/ARM-USART2.md).
- The redundant-CPU field (HR 9 low) is `0x00` on the 12000XP `ceaa` — consistent
  with that build folding redundancy differently from the 18kPV.

A FW-version mismatch here is what surfaces as warning **W008** (ARM-computed; see
[`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).
