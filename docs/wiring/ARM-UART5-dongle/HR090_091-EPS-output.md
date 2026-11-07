# HR 90-91 — EPS output V/F set

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | values |
|---|---|---|---|
| HR 90 | EPSVoltageSet | 1 V | 208 / 230 / 240 / 277 |
| HR 91 | EPSFreqSet | 1 Hz | 50 / 60 |

## Side-effects of writing

**Off-grid (EPS) output voltage/frequency targets** — persisted to config flash
and pushed to the DSP (which generates the EPS output) in the config snapshot over
USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `EPS Voltage Set` (**default 110/220**; options 120/240, 127/220 three-phase, 100/200 split-phase, 120/208, 115/230) and `EPS Frequency Set` (**default 60Hz** | 50Hz).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 90 (EPSVoltageSet):** HMI enum edit — [`test_hmi.c`](../../../tests/test_hmi.c) (`HR_EPS_VOLT_SET`, clamp + write).
- **DSP config-push (T10/T25):** HR 90 and HR 91 share the packed config-frame byte **block 0 @0x1a** (low byte of DSP `0xAD83`): HR 90 EPS voltage → a 2-bit select enum (`208→0, 277→1, 230→2, 240→3`), HR 91 EPS frequency → bit `0x08` when 60 Hz (factory-decoded). Routing verified ours==factory in [`test_dsp_push.py`](../../../tests/test_dsp_push.py) `test_{factory,ours}_grid_push_matches_spec` (`GRID_PUSH`); the enum + freq bit are locked in [`test_dsp_config.c`](../../../tests/test_dsp_config.c). See the [HR→push matrix](../ARM-USART3-DSP/hr-push-matrix.md).
