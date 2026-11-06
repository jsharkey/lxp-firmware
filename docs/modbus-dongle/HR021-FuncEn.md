# HR 21 — FuncEn (function-enable bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

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
the config snapshot over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)).
Several bits gate real-time power behaviour the DSP runs (EPS, anti-island, LVRT,
forced charge/discharge, feed-in). Bit 9 `SetToStandby` drives the operating
mode/standby. **Open:** per-bit mapping into the DSP config block.

## On the LCD (EG4 12000XP manual)

Several **Application-tab** toggles live in feature-enable words: the manual exposes `EPS Voltage Set`, `EPS Frequency Set`, `AC Input Range`, `PV Grid Off`, `N-PE Connect (Inner)`, `PV Arc`, `RSD Enable` there. The exact bit→toggle mapping across FuncEn (HR 21) / FunctionEn1 (HR 110) / stSysEnable (HR 120) is not fully pinned — treat the HMI labels as the user-facing names for those bits.
