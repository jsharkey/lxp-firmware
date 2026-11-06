# HR 120 — stSysEnable (bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| bit | field | values |
|---|---|---|
| 0 | HalfHourACChrStartEn | 0/1 |
| 1-3 | ACChargeType | 0 disable, 1 by time, 2 by voltage, 3 by SOC |
| 4-5 | DischgCtrlType | 0 by voltage, 1 by SOC, 2 both |
| 6 | OnGridEODType | 0 by voltage, 1 by SOC |
| 7 | GenChargeType | 0 by battery voltage, 1 by SOC |

## Side-effects of writing

**System-behaviour mode selectors** (how AC-charge, discharge control, on-grid EOD
and generator-charge decide their thresholds). Persisted to config flash and
pushed to the DSP in the config snapshot over USART3
([`docs/08`](../08-arm-dsp-config-protocol.md)). These select *which* of the
threshold registers (voltage vs SOC) are active.
