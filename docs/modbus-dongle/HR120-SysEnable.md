# HR 120 — stSysEnable (bitfield)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| bit | field | values |
|---|---|---|
| 0 | HalfHourACChrStartEn | 0/1 — gates the OptimalChg_DisChg half-hour table ([HR 126-131](HR126_131-OptimalChg_DisChg.md)); **dormant in ceaa-07xx** (docs/31 Q5) |
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

## On the LCD (EG4 12000XP manual)

Mode-selector bits exposed on the LCD: `Discharge Control` = Use Vol | **Use SOC** (Discharge tab, DischgCtrlType); `Generator Charge Type` = Use Vol | **Use SOC** (Charge tab, GenChargeType); the AC-charge method selector `AC Chg Based On` (ACChargeType).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **HR 120 (stSysEnable):** [`test_dsp_config.c`](../../tests/test_dsp_config.c) sets `HR_SYS_ENABLE` into the config push. Its **ACChargeType** field is exercised as the AC-charge gate (config +0x33) by [`test_timewindow.py`](../../tests/test_timewindow.py) / [`timewindow_contract.py`](../../tests/timewindow_contract.py) `acchg`.
