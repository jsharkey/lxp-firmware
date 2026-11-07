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

**Timing (OSS decision, T12).** Ours applies the new address **after the write's
own reply has gone out on the OLD address**, then adopts it for the next request —
no reboot. If the slave switched mid-transaction, its own ACK would leave on the
new address and the requester (still on the old one) would never see it; so the
change is deferred by one transaction (`g_pending_com_addr`, applied in the main
loop after `mb_port_poll`). On boot the stored value (1..150) is loaded as the live
address. The factory's exact apply-moment is not observable in this harness: the
factory answers on USART3 (`ModbusDsp`) while its **dongle UART5** slave task is not
scheduled by the sim — a separate factory-dongle harness, not the T02 USART2 work
(which is done). "Immediate, after the reply" is our contract.
See [`docs/31`](../../31-factory-quirks.md) "OSS behaviour decisions".

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **HR 15 (Com Addr):** write-single path — [`test_modbus.c`](../../../tests/test_modbus.c) writes `HR_COM_ADDR` and checks the echo.
- **Write validation (T04):** [`test_settings_validate.py`](../../../tests/test_settings_validate.py) / [`settings_contract.py`](../../../tests/settings_contract.py) — in-range `10` accepted, `151` (> max 150) rejected with Modbus exception 3; host [`test_settings_validate.c`](../../../tests/test_settings_validate.c).
- **Live address change (T12):** [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_comaddr_changes_slave_address_live` — a write of `7` sent to address 1 is ACKed on 1, after which the slave answers on 7 and is silent on 1 (no reboot).
