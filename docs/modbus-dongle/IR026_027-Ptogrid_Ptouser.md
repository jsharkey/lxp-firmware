# IR 26-27 — Ptogrid / Ptouser

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

| reg | name | unit | range | note |
|---|---|---|---|---|
| IR 26 | Ptogrid | 1 W | 0-65535 | export power to grid |
| IR 27 | Ptouser | 1 W | 0-65535 | import power from grid |

## Where the data comes from

**ARM-computed** grid-direction power ([`docs/22`](../22-arm-dsp-core-split.md)).
The AC-First time-window decision influences grid routing but is evaluated
ARM-side and surfaced separately (IR 126 bit 8) — it is **not** pushed to the DSP
([`docs/25`](../25-modbus-register-spaces.md)).

## On the LCD (EG4 12000XP manual)

DATA MENU **Grid tab**: `Pexport` = power output to grid (0 on this off-grid inverter), `Pimport` = power input from grid.
