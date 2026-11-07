# HR 9-10 — firmware versions (per processor)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg·byte | field | processor | value in ceaa-07xx |
|---|---|---|---|
| 9 low | Slave/Redundant CPU ver | safety CPU | const `0x00` (not populated on 12000XP) |
| 9 high | Communication CPU ver | **this STM32 ARM** | const (ARM's baked-in build ver) |
| 10 low | Control CPU ver | TI C2000 **DSP** | from USART2 bank `BANK+2` (`0x2000ce5e`; bank base corrected to `0x2000ce5c` in T02a) |
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

**W008 is a model-IDENTITY compare, not a numeric version compare** (pinned once the
USART2 wire ran — T02b; see [`IR060_063-FaultCode_WarningCode`](IR060_063-FaultCode_WarningCode.md)).
The classifier (`sub_0801a93a`) case-insensitively compares the **peer identity** the
safety CPU relays in its tag-0 record (frame `+0x15..+0x18` → bank `+3..6`) against the
model code **"ceaa"**, and sets the "version-OK" bit (health word `0x2000d890` **bit 10**)
only on a match. A non-matching identity leaves that bit clear. This is proven both
directions on the factory (`test_usart2_identity_drives_version_health_bit`): "ceaa"
→ bit 10 set, "zzzz" → bit 10 clear. **Open (T06b-adjacent):** in the bare harness the
health bit does **not** surface as a WarningCode bit at `STATE+0x9c` (it stays 0 either
way), so how the version-OK bit gates into the Modbus WarningCode is not yet pinned.

**Our firmware (T12).** We report our *own* build identity rather than mimicking the
factory constants: on boot HR 9 high (Communication CPU) is seeded from
`OSS_ARM_COMMS_VER` and HR 10 high (FW version code) from `OSS_FW_VERSION_CODE`
(both `0x01` for now, placed in the high byte to match the factory byte layout). HR 9
low (redundant CPU) stays `0x00`, and **HR 10 low (DSP version) is a live read-back of
the relayed USART2 bank byte** (`bank+2`), refreshed each loop in `main.c` — exactly as
the factory sources it (proven by `test_usart2_dsp_version_reaches_hr10_low`). **W008**
is now implemented (`src/safety/safety_cpu.c`): we run the same case-insensitive
identity compare against the active variant's `model_code` ("ceaa" on the 12000XP) and
raise W008 (WarningCode bit 8) while the relayed identity has not matched, **latched**
clear once it does — mirroring the factory's latched health bit. The factory's own
gating of that bit into the Modbus WarningCode is unconfirmed (see above), so this is a
spec-aligned interpretation (`WARN_FW_VERSION_MISMATCH`, `inv/faults.h`), noted in
[`docs/31`](../../31-factory-quirks.md) "OSS behaviour decisions".

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — these are **read-only**; a dongle write draws Modbus exception 4 (SLAVE_FAILURE) and stores nothing. Host [`test_settings_validate.c`](../../../tests/test_settings_validate.c) covers both HR 9 and HR 10.
- **W008 identity compare + DSP version (T12):** host [`test_w008.c`](../../../tests/test_w008.c) (`make test`) covers the case-insensitive identity match, the latch, and the `bank+2` DSP-version read. Factory oracle: [`test_arm_sim_factory_only.py`](../../../tests/test_arm_sim_factory_only.py) `test_usart2_identity_drives_version_health_bit` (identity → health bit 10, both directions) and `test_usart2_dsp_version_reaches_hr10_low` (relayed DSP version → HR 10 low over Modbus). Ours: [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_w008_tracks_relayed_peer_identity`.
