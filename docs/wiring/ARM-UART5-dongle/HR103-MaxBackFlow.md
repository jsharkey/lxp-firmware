# HR 103 — MaxBackFlow (feed-in limit)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md).

| reg | name | unit | note |
|---|---|---|---|
| HR 103 | MaxBackFlow | % | feed-in grid power set |

## Side-effects of writing

**Export/feed-in power cap** — persisted to config flash and pushed to the DSP
(which limits export) in the config snapshot over USART3
([`docs/08`](../../08-arm-dsp-config-protocol.md)).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Flash persistence (T03):** HR 103 is pinned in the shared `SETTINGS_MAP` ([`settings_persist_contract.py`](../../../tests/settings_persist_contract.py)) and round-trips **cross-image** (ours writes the factory on-flash byte layout; the factory writes and ours reads it back) in [`test_persist_crossimage.py`](../../../tests/test_persist_crossimage.py) (`test_ours_writes_the_factory_byte_layout_full` / `test_factory_persists_ours_reads_by_class`), plus single-image cold-boot via `test_settings_persist_across_cold_boot` ([`test_arm_sim.py`](../../../tests/test_arm_sim.py)).
