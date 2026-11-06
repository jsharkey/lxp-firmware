# IR 121-126 — generator telemetry

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | source |
|---|---|---|---|
| IR 121 | GenVolt | 0.1 V | USART2 bank `BANK+0x28` (shared w/ VacS) |
| IR 122 | GenFreq | 0.01 Hz | USART2 bank `BANK+0x62` |
| IR 123 | GenPower | 1 W | ARM-computed |
| IR 124 | Egen_day | 0.1 kWh | ARM-accumulated |
| IR 125-126 | Egen_all L/H | 0.1 kWh | ARM-accumulated (32-bit) |

## Where the data comes from

**Generator voltage/frequency: the USART2 bank** at the offsets above
([`docs/33`](../33-usart2-telemetry-bank.md)). **Power/energy: ARM-computed /
accumulated.** Note IR 126 doubles as a status word in ceaa-07xx (bit 8 = AC-First
window active) — a space/usage nuance flagged in
[`docs/25`](../25-modbus-register-spaces.md); do not assume IR 126 is purely
generator energy for this image.

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Vgen` = generator voltage, `Fgen` = generator frequency.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../AGENTS.md))._

- **IR 122 (Fgen):** safety-CPU telemetry — [`arm_sim_contract.py`](../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`gen_freq`), asserted by `test_safety_cpu_telemetry_reaches_modbus`.
- **IR 126 bit 8 (AC-First active):** [`test_arm_sim.py`](../../tests/test_arm_sim.py) `test_modbus_acfirst_window_tracks_rtc` — the only externally observable AC-First signal, swept across the window edges vs the RTC.
- **IR 121 / 123 / 124 / 125 (Vgen, Egen day/all):** _No automated test exercises this register yet — a focused test is welcome._
