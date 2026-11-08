# IR 121-126 — generator telemetry

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | source | classification |
|---|---|---|---|---|
| IR 121 | GenVolt | 0.1 V | safety bank `+0x28` — **the VacS word** | **live mirror** (= IR 13) |
| IR 122 | GenFreq | 0.01 Hz | safety bank `+0x62` | live telemetry |
| IR 123 | GenPower | 1 W | ARM-computed | computed (0 w/o gen running) |
| IR 124 | Egen_day | 0.1 kWh | ARM-accumulated | accumulated |
| IR 125-126 | Egen_all L/H | 0.1 kWh | ARM-accumulated (32-bit) | accumulated / persisted |

## Where the data comes from

**Generator voltage (IR 121): a live mirror of VacS (IR 13).** Both are served from
the *same* safety-bank word `+0x28` — the generator input shares the grid S-phase
sense on this image, so **IR 121 == IR 13**. Verified empirically (T26): feeding a
USART2 tag-2 frame carrying `grid_s` at frame `+0x23` makes IR 121 and IR 13 both read
the fed value on the factory image (`ceaa-07xx`), and our firmware now serves the same
mirror ([`safety_cpu.c`](../../../src/safety/safety_cpu.c) `PUT(IR_GEN_VOLT, +0x28)`).
This corrects the earlier "shared w/ VacS" note from an inference to a proven mirror.

**Generator frequency (IR 122): the safety bank** `+0x62`
([`docs/33`](../../33-usart2-telemetry-bank.md)).

**Power/energy (IR 123/124/125): ARM-computed / accumulated**, *not* reachable through
telemetry ingest alone — on a quiescent image (no generator running) IR 123 (GenPower)
and IR 124 (Egen_day) read **0**, while IR 125 (Egen_all L) reads back the **persisted**
accumulator from config flash. A parity test for these needs the generator-charge path
active + the energy accumulator exercised (relate to the IR 28-59 energy counters and
T16 generator work) — a characterized hand-off, not yet a vectored test.

Note IR 126 doubles as a status word in ceaa-07xx (bit 8 = AC-First window active) — a
space/usage nuance flagged in [`docs/25`](../../25-modbus-register-spaces.md); on a
quiescent image IR 126 reads the `da3a` status mirror (e.g. `0x10`), **not** the
energy-high word, so do not assume IR 126 is purely generator energy for this image.

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Vgen` = generator voltage, `Fgen` = generator frequency.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **IR 122 (Fgen):** safety-CPU telemetry — [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `SAFETY_TELEMETRY` (`gen_freq`), asserted by `test_safety_cpu_telemetry_reaches_modbus`.
- **IR 126 bit 8 (AC-First active):** [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_modbus_acfirst_window_tracks_rtc` — the only externally observable AC-First signal, swept across the window edges vs the RTC.
- **IR 121 (Vgen):** the live mirror of IR 13 — [`test_arm_sim.py`](../../../tests/test_arm_sim.py) `test_gen_volt_mirrors_grid_s` feeds a USART2 tag-2 frame and asserts IR 121 == IR 13 == the fed grid_s, on **both** images (factory oracle + ours).
- **IR 123 / 124 / 125 (GenPower, Egen day/all):** _ARM-computed / accumulated; not exercised by telemetry ingest (read 0 / persisted on a quiescent image). A parity test needs the generator-charge path + energy accumulator active — characterized above, test welcome._
