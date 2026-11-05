# The ARM RTC software calendar, and the energy daily-rollover (hand-off)

Two things: (1) the **proven** ARM real-time-clock calendar and its advance
function — the "walk the clock forward" mechanism every time-of-day feature keys
off — and (2) a **hand-off** for the still-blocked energy-counter daily rollover
(IR 28-37) that builds on it.

> **Image.** All addresses here are the **07-series** `ceaa-07xx_vE_260214`
> (the 522 KB App-at-`0x08005000` build; my analysis image). The committed
> `reference/com_flat.bin` the default sim suite loads is the **05-series**
> (`0x2000a718` RTC, `0x20009854` settings, `0x20009e54` telemetry bank — see
> `tests/timewindow_contract.py` profiles and docs/33); its RTC-advance is a
> *different* function. The test below self-guards and SKIPs on non-07 images.

## 1. The RTC software calendar — proven (dynamic, 07-series)

The ARM keeps a 7-byte software calendar at **`0x2000d850`**:

| offset | field | range |
|---|---|---|
| `+0` | second | 0-59 |
| `+1` | minute | 0-59 |
| `+2` | hour | 0-23 |
| `+3` | day-of-month | 1-28/29/30/31 |
| `+4` | month | 1-12 |
| `+5` | year | offset from 2000 (e.g. 24 = 2024) |
| `+6` | weekday | computed |

*(This is the same base the AC-First window evaluator reads for `+1`/`+2`;
docs/25.)*

**`sub_08018bc0` is the 1-second tick / calendar-advance.** Each call bumps a
prescaler byte at **`0x2000dba7`** and advances the calendar on **every second
call** (so 2 calls = +1 s). It carries `sec→min→hour→day→month→year`, using
`sub_08016914` for **days-in-month** and `sub_08016328(day, month, 2000+year)`
for the weekday — so **leap years are handled**. It is self-contained (touches
only the calendar + those two pure helpers), callable in isolation with no boot.

**Validated** by seeding the calendar and walking it (isolated calls under
`tools/arm_sim.py`):

| from | +secs | to | checks |
|---|---|---|---|
| 2024-01-01 00:00:00 | 1 | 00:00:01 | tick |
| …23:59:58 | 4 | +1 min / +1 hr / +1 day | carry chain |
| 2024-04-30 23:59:58 | 4 | 2024-05-01 | 30-day month |
| 2023-02-28 23:59:58 | 4 | 2023-03-01 | **non-leap** Feb (no 29th) |
| 2024-02-28 23:59:58 | 4 | 2024-02-29 | **leap** Feb |
| 2024-12-31 23:59:58 | 4 | 2025-01-01 | year roll |

**Test:** `tests/test_arm_sim_factory_only.py::test_rtc_calendar_walks_forward`
(07-series only; SKIPs elsewhere).

## 2. The energy counters (what we're aiming at)

The dongle exposes energy integrals the ARM maintains
([`input-028_059-energy-counters`](modbus-dongle/input-028_059-energy-counters.md)):

- **Daily** IR 28-37 (u16, 0.1 kWh) — **reset at the day boundary**.
- **Cumulative** IR 40-59 (u32 L/H, 0.1 kWh) — **persist**; cleared only via
  `HR 11` `EnergyRecordClr` ([`holding-011-ResetSetting`](modbus-dongle/holding-011-ResetSetting.md)).

Accumulation (`energy += power·Δt`) is **tick/power-driven**, not clock-driven;
the **RTC drives only the daily reset/rollover** (§1 is that clock). So "walk the
RTC forward" exercises the rollover, not the accumulation rate.

## 3. Hand-off — the daily rollover is not yet located (07-series)

The daily-rollover test is **blocked** on RE that is not done. Evidence and
dead-ends from this pass (so the next agent doesn't repeat them):

- **The counters are inert at cold boot.** On the 07-series, IR 28-37, IR 40-59
  and RunningTime (IR 69-70) all read **0** right after boot. The accumulator
  appears **gated on operational state** (a running mode with DSP/safety-CPU
  power telemetry), so there is nothing to observe — or roll over — cold.
- **`HR 11` `EnergyRecordClr` is not observably handled cold** — a `0x06` write
  of bit 0 draws no echo and zeroes nothing in a booted-but-idle run; the
  per-bit command handler is unconfirmed (docs/11 note "confirm handler per bit").
- **Ruled out:** `0x2000d4f8` (a tight 20-byte block a day-reader zeroes) is
  **not** the daily counters — `sub_0800aea8` formats an ASCII `YY-MM-DD HH:MM:SS`
  timestamp string there (digits via `sub_08005f48`, separators `-`/` `/`:`).
- **Not located:** the FC04 register getter that serves IR 28-37 / 40-59 (so the
  energy struct's RAM address is unknown on this image); empirical read-traces
  are too noisy (a full Modbus transaction churns RAM nondeterministically), and
  the getter is absent from the current symbol set.
- **Lead:** the ~12 KB supervisor **`sub_0801f596`** reads the calendar day field
  (`0x2000d853`) and does extensive block stores — a likely home for the
  accumulation and/or the day-change rollover. Start there.

**What's needed next:** (a) locate the FC04 getter → the daily (IR 28-37) and
cumulative (IR 40-59) struct addresses; (b) find the day-change detector keyed on
`0x2000d853` that zeroes the daily block (and whether it carries the day's total
into cumulative); (c) establish the operational gating. Then the test is a
grey-box walk: seed a nonzero daily counter, advance the RTC across midnight with
`sub_08018bc0` (§1), and assert the daily counters reset while the cumulative
ones persist — then TDD our firmware to match.

## Provenance

- **Proven (dynamic, 07-series):** the calendar layout `0x2000d850+0..+6`, the
  advance function `sub_08018bc0` (prescaler `0x2000dba7`, 2 calls/s), the carry
  chain, days-in-month and leap handling — all validated by walking the clock.
- **Open / inferred:** everything in §3 (energy struct, accumulator, daily
  rollover, gating) — not yet located on the 07-series.
