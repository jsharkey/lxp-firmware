# The ARM RTC software calendar, and the energy daily-rollover (hand-off)

Two things: (1) the **proven** ARM real-time-clock calendar and its advance
function — the "walk the clock forward" mechanism every time-of-day feature keys
off — and (2) a **hand-off** for the still-blocked energy-counter daily rollover
(IR 28-37) that builds on it.

> **Image.** All addresses here are the **07-series** `ceaa-07xx_vE_260214` (the
> 522 KB App-at-`0x08005000` build) — the **current canonical reference image**
> (`reference/ceaa-07xx_vE_260214.bin`). The older **05-series**
> (`ceaa-05xx_com_vE_250325`, `0x2000a718` RTC / `0x20009854` settings /
> `0x20009e54` telemetry bank — the `ceaa05` profile in
> `tests/timewindow_contract.py`) has a *different* RTC-advance function, so the
> test below self-guards and SKIPs on non-07 images.

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

## 1a. Simulator RTC control + our firmware's RTC (both sides of the contract)

The harness (`tools/arm_sim.py`) now owns a general wall-clock control so any
test can shift time around cheaply, against **either** firmware:

- `sim.configure_rtc(calendar, tick=None, prescale=None, calls_per_sec=1)` —
  register an image's 7-byte calendar and its 1 s advance function.
- `sim.set_rtc(sec, minute, hour, day, month, year)` — force the clock (a direct
  RAM poke; no boot).
- `sim.advance_rtc(seconds)` — walk it forward by calling the firmware's **own**
  tick, so its real carry / days-in-month / leap logic runs.
- `sim.get_rtc()` → `(sec, minute, hour, day, month, year)`.

Our firmware gained a matching real RTC, **`src/rtc/rtc.c`** (`g_rtc`,
`rtc_tick()`, `rtc_set_from_modbus()`, `rtc_now_minutes()`): the same 7-byte
layout and carry/leap rules as the factory. It is **settable from HR 12-14**,
**ticks at 1 Hz** from the main loop, and now **drives the AC-First window
evaluator** (so our clock actually advances, instead of reading the static
time registers). Host-tested in `tests/test_rtc.c` (`make test`).

**Tests (shared spec, both images):** the `RTC_WALK` vectors in
`tests/arm_sim_contract.py` are asserted against **ours** (by symbol,
`test_arm_sim_self_only.py`) and the **factory** (by address,
`test_arm_sim_factory_only.py`) — the same one-spec/both-images pattern as the
relay and safety-telemetry contracts. The factory side is 07-series-specific and
SKIPs on other images (e.g. the 05-series `reference/ceaa-05xx_com_vE_250325.bin`).

## 2. The energy counters (what we're aiming at)

The dongle exposes energy integrals the ARM maintains
([`IR028_059-energy-counters`](modbus-dongle/IR028_059-energy-counters.md)):

- **Daily** IR 28-37 (u16, 0.1 kWh) — **reset at the day boundary**.
- **Cumulative** IR 40-59 (u32 L/H, 0.1 kWh) — **persist**; cleared only via
  `HR 11` `EnergyRecordClr` ([`HR011-ResetSetting`](modbus-dongle/HR011-ResetSetting.md)).

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
