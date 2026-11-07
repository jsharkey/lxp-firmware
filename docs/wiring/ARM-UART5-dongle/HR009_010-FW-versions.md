# HR 9-10 — firmware versions (per processor)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg·byte | field | processor | value in ceaa-07xx |
|---|---|---|---|
| 9 low | Slave/Redundant CPU ver | safety CPU | const `0x00` (not populated on 12000XP) |
| 9 high | Communication CPU ver | **this STM32 ARM** | const (ARM's baked-in build ver) |
| 10 low | Control CPU ver | TI C2000 **DSP** | from USART2 bank `BANK+2` (`0x20009e56`) |
| 10 high | FW version code | — (ARM build code) | const |

## Where the data comes from

These live in the *holding* space but are effectively **read-back status**, each a
FW version byte. Traced in the factory image via the holding getter `fn_ceaa`
([`docs/32`](../../32-firmware-version-registers.md)):

- The **only** version read from another processor at runtime is the **Control CPU
  (DSP) version, HR 10 low** — it comes from the **USART2 bank byte +2**, written
  by the USART2 parser `sub_080241a8`. So the DSP's version reaches the dongle the
  same relayed way as its mode/telemetry: **over USART2 via the safety CPU**, not
  on the direct USART3/DSP link. See [`docs/wiring/ARM-USART2`](../../wiring/ARM-USART2-safety.md).
- The redundant-CPU field (HR 9 low) is `0x00` on the 12000XP `ceaa` — consistent
  with that build folding redundancy differently from the 18kPV.

A FW-version mismatch here is what surfaces as warning **W008** (ARM-computed; see
[`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).

**Our firmware (T12).** We report our *own* build identity rather than mimicking the
factory constants: on boot HR 9 high (Communication CPU) is seeded from
`OSS_ARM_COMMS_VER` and HR 10 high (FW version code) from `OSS_FW_VERSION_CODE`
(both `0x01` for now, placed in the high byte to match the factory byte layout). HR 9
low (redundant CPU) stays `0x00` and HR 10 low (DSP) is a live read-back of the
relayed USART2 bank byte, exactly as the factory sources it. We do **not** raise
W008 from a version compare yet: the mismatch test needs the DSP/safety-CPU version
feed that is still T02-blocked, so W008 is held clear until a real relayed version is
in hand rather than fired on our placeholder constants. See
[`docs/31`](../../31-factory-quirks.md) "OSS behaviour decisions".

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — these are **read-only**; a dongle write draws Modbus exception 4 (SLAVE_FAILURE) and stores nothing. Host [`test_settings_validate.c`](../../../tests/test_settings_validate.c) covers both HR 9 and HR 10.
