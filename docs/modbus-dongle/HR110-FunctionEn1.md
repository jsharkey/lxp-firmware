# HR 110 — FunctionEn1 (bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| bit | field | note |
|---|---|---|
| 0 | ubPVGridOffEn | 0 disable / 1 enable |
| 1 | ubFastZeroExport | |
| 2 | ubMicroGridEn | |
| 3 | ubBatShared | |
| 4 | ubChgLastEn | |
| 5-6 | CTSampleRatio | 0: 1/1000, 1: 1/3000 |
| 12-13 | PVCTSampleRatio | 0: 1/1000, 1: 1/3000 |

## Side-effects of writing

**Secondary feature-enable word** incl. CT (current-transformer) sample ratios —
persisted to config flash and pushed to the DSP in the config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)). The CT ratios affect how metering
currents are scaled. (A further `uFunctionEn2` word is HR 179, index-only.)

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `PV Grid Off` (**default Disable**) = `ubPVGridOffEn` (bit 0). `Battery Shared` (**default Disabled**) is the parallel battery-sharing enable.
