# HR 105 — EOD (end-of-discharge SOC)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | range |
|---|---|---|---|
| HR 105 | EOD | % | 10-90 |

## Side-effects of writing

**End-of-discharge SOC cutoff** — persisted to config flash and pushed to the DSP
in the config snapshot over USART3 ([`docs/08`](../../08-arm-dsp-config-protocol.md)).
Related on-grid/EPS EOD variants: HR 120 bit6 OnGridEODType, HR 125
SOCLowLimitForEPSDischg (index-only).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Discharge tab**: `On Grid EOD Volt` (**default 42.0V**). Related Discharge-tab settings: `Discharge Cut-off Volt` (**default 42.0V**, HR 100), `Battery Warning Volt` (**default 44.0V**).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 105 (EOD):** [`test_dsp_config.c`](../../../tests/test_dsp_config.c) sets `HR_EOD` and confirms it is carried in the config push.
- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `50` accepted, `9` (< min 10) rejected with Modbus exception 3, but `91` (> spec max 90) is **accepted** — the factory enforces only the lower bound ([`docs/31`](../../31-factory-quirks.md) Q6, replicated for parity). Host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
