# HR 15 — Com Addr (Modbus slave address)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | range |
|---|---|---|
| HR 15 | Com Addr | 0-150 |

## Side-effects of writing

**Changes the ARM's own Modbus slave address on the dongle bus** — the `addr`
byte the dongle must use to reach this inverter. Persisted to config flash.
Self-referential: after a successful write the inverter answers on the new
address.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 15 (Com Addr):** write-single path — [`test_modbus.c`](../../../tests/test_modbus.c) writes `HR_COM_ADDR` and checks the echo.
- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `10` accepted, `151` (> max 150) rejected with Modbus exception 3; host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
