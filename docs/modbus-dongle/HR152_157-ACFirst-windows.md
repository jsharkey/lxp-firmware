# HR 152-157 — AC-First load time windows

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

Three AC-First windows, each start/end packed `low=hour(0-23)`, `high=minute(0-59)`:

| window | start | end |
|---|---|---|
| 0 | HR 152 | HR 153 |
| 1 | HR 154 | HR 155 |
| 2 | HR 156 | HR 157 |

## Side-effects of writing

**Persisted to config flash and evaluated ARM-side against the clock** — this is
the proven AC-First observable. `sub_080352d0` reads the RTC and walks these three
windows (config buffer `0x2000c85c+0x64` = HR 152-157); a window is active iff
`start ≤ now < end` (start-inclusive, end-exclusive, with midnight wrap). The
result funnels to **IR 126 bit 8** ("AC-First window active now") and is **not
pushed to the DSP** — the derived verdict stays ARM-side. Full trace, including the
black-box test: [`docs/25`](../25-modbus-register-spaces.md) §3.

This controls *when* AC-first applies; the *priority mode itself* is
[`HR145-OutputPrioConfig`](HR145-OutputPrioConfig.md) (value 2).

## On the LCD (EG4 12000XP manual)

SETTINGS → **Application tab**: `AC First` — P1/P2/P3 `Start`/`End` (**factory default 00:00 / 00:00**, range 00:00-23:59). Manual: the time windows during which the inverter uses **only AC** to power loads and uses all PV to charge the battery.
