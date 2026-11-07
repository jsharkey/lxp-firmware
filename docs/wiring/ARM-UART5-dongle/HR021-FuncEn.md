# HR 21 — FuncEn (function-enable bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| bit | field | bit | field |
|---|---|---|---|
| 0 | EPSEn (off-grid) | 8 | SWSeamlesslyEn |
| 1 | OVFLoadDerateEn | 9 | SetToStandby (0 standby / 1 power on) |
| 2 | DRMSEn | 10 | ForcedDischgEn |
| 3 | LVRTEn | 11 | ForcedChgEn |
| 4 | AntiIslandEn | 12 | ISOEn |
| 5 | NeutralDetectEn | 13 | GFCIEn |
| 6 | GridOnPowerSSEn | 14 | DCIEn |
| 7 | ACChargeEn | 15 | FeedInGridEn |

## Side-effects of writing

**Core feature-enable word** — persisted to config flash and pushed to the DSP in
the config snapshot over USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)).
Several bits gate real-time power behaviour the DSP runs (EPS, anti-island, LVRT,
forced charge/discharge, feed-in). Bit 9 `SetToStandby` drives the operating
mode/standby. **Open:** per-bit mapping into the DSP config block.

## On the LCD (EG4 12000XP manual)

Several **Application-tab** toggles live in feature-enable words: the manual exposes `EPS Voltage Set`, `EPS Frequency Set`, `AC Input Range`, `PV Grid Off`, `N-PE Connect (Inner)`, `PV Arc`, `RSD Enable` there. The exact bit→toggle mapping across FuncEn (HR 21) / FunctionEn1 (HR 110) / stSysEnable (HR 120) is not fully pinned — treat the HMI labels as the user-facing names for those bits.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 21 (FuncEn):** [`test_dsp_config.c`](../../../tests/test_dsp_config.c) sets `HR_FUNC_EN` (ACChargeEn) and confirms it flows into the config push.
- **DSP config-push (T10/T25):** FuncEn is bit-remapped into the config frame **block 0 @0x2c** (→ DSP `0xAD85` low byte): bit1→`0x10`, bit4→`0x08`, bit6→`0x04`, bit10→`0x20`, bit11→`0x40` (factory-decoded). Routing verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH`); the bit remap is locked in [`test_dsp_config.c`](../../../tests/test_dsp_config.c). See the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md).
- **Persistence (slot 0 `+0x13`):** [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) round-trips it cross-image. NB the factory does **not** echo FuncEn verbatim on read — it OR-s a capability bit (`stored | 0x200`), so the test checks `(got & written) == written`. See [`docs/31`](../../31-factory-quirks.md) Q8.
