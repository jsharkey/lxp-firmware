# HR 20 — PVInputModel

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | range | note |
|---|---|---|---|
| HR 20 | PVInputModel | 0-4 (0-7 for 12K hybrid) | PV routing / parallel config |

0 no PV, 1 PV1, 2 PV2, 3 two parallel PV, 4 two separate PV (18kPV extends 0-7).

## Side-effects of writing

**A DSP-relevant configuration value** — persisted to config flash and pushed to
the DSP as part of the full config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)/[`docs/10`](../../10-dsp-config-field-map.md),
[`docs/wiring/ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md)). Tells the power stage how the
PV inputs are wired. **Open:** its exact offset in the DSP config block.

## On the LCD (EG4 12000XP manual)

SETTINGS → **Common tab**: `PV Input Mode` = `DC source input` | `Two MPPT connect to different strings` — **factory default: Two MPPT to different strings**. ('Same string' parallels both strings into one MPPT at the inverter.)

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `3` accepted, `8` (> max 7) rejected with Modbus exception 3; host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
- **Flash persistence (T03):** HR 20 is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)).
