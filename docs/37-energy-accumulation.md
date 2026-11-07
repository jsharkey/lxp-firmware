# Accumulated energy counters — struct, accumulator, and daily rollover

Resolves the open items from [`docs/36 §3`](36-rtc-calendar-and-energy-rollover.md):
the energy-counter **RAM struct is now located**, the **accumulator is found and
validated**, and the **daily-rollover trigger is characterised** (located as a
mechanism, now driven in isolation and asserted against both images — see §4).

> **Image:** `ceaa-05xx_com_vE_250325.bin` — the **05-series** (`ceaa-05xx`) build.
> ⚠️ This is the older 05 image, **not** the committed canonical reference
> (`reference/ceaa-07xx_vE_260214.bin`, the 07-series). Every address below is a
> **05-image** address and does not transfer to the 07 image (different base /
> layout — see [`docs/11`](11-12000xp-revisions.md)):
> settings `0x20009854`, telemetry bank `0x20009e54`, RTC calendar `0x2000a718`
> (the `ceaa05` profile in `tests/timewindow_contract.py`; *not* the 07-series
> `0x2000d850`). Addresses are from this image; symbol-map regenerations relabel
> functions, so code is cited by address.

## 1. The energy struct (base `0x20009954`)

Found by calling the input getter `sub_0803289c` in isolation over a per-word
**marker image** (each RAM u16 = its own index), so the getter's return value
names the exact source address of every register (the noisy full-Modbus traces
docs/36 tried could not). Base **`0x20009954`** (just past the settings struct
`0x20009854`). Register → offset (proven):

| input reg | field | struct offset | width |
|---|---|---|---|
| IR 69/70 | RunningTime | `+0x16` | u32 |
| IR 28 | Epv1_day | `+0x26` | u16 |
| IR 29 | Epv2_day | `+0x28` | u16 |
| IR 31 | Einv_day | `+0x34` | u16 |
| IR 40/41 | **Epv1_all** | `+0x52` | u32 L/H |
| IR 42/43 | Epv2_all | `+0x56` | u32 |
| IR 46/47 | Einv_all | `+0x6e` | u32 |

Daily counters (u16) cluster around `+0x22…+0x38`; cumulative counters (u32) around
`+0x4a…+0x76`; per-channel integration **sub-accumulators** (u32) around `+0xa2…+0xce`.

## 2. The accumulator (fns `0x0801fbc4`, `0x0801f960`)

Per accumulation tick, for each channel, **gated on a running operating state**:

```
sub[ch] += power[ch] >> 1;                 // integrate at half rate
if (sub[ch] >= 0x0036EE81 /*3,600,001*/) { // crossed one 0.1 kWh quantum
    day[ch]++;  all[ch]++;  sub[ch] -= 0x0036EE80 /*3,600,000*/;
}
```

- **`power[ch]`** is read from the classified **STATUS struct `0x2000a0d8`** (e.g.
  Epv1 ← `+0x28`, Epv2 ← `+0x2c`, Einv ← `+0x30`), which the ARM builds from its
  **safety-CPU / DSP telemetry** (docs/22/30) — so the integral's source is the
  link telemetry the user expected, not an instantaneous bank field.
- **Gate:** `0x0801fbc4` runs only while the safety-CPU bank state
  `[0x20009e55] >= 3`; `0x0801f960` additionally selects channels by specific
  states (`0x10` bat-ongrid, `0x04` PV-ongrid, `0x40`/`0x80` off-grid, …). This is
  exactly the "gated on operational state → inert cold" docs/36 observed.

**Epv1 specifically** (`0x0801fbc4`): `sub[+0xaa] += STATUS[+0x28] >> 1`; at the
threshold, `day[+0x26]++` (IR 28) and `all[+0x52]++` (IR 40). **Validated** by
seeding the state + PV1 power and calling the real function — Epv1_all (IR 40, via
the getter) counts up one per tick at `power/2 == threshold`, and nothing moves
when the state gate is below 3. See [`tests/test_energy.py`](../tests/test_energy.py).

The per-tick driver `sub_0801fc3c` snapshots the counters to mirrors
(`0x2000a638` daily / `0x2000a4bc` cumulative) for a dirty-check/flash-persist, then
calls both accumulators and bumps RunningTime (2 calls/s).

## 3. The getter (`sub_0803289c`)

The FC04 input-register getter docs/36 could not find **is** `sub_0803289c` (the
same getter that serves IR 0 etc.). Its energy cases read the struct above; the
32-bit cumulative pairs are served as reg → low u16 / reg+1 → high u16.

## 4. Daily rollover — the calendar-date reset (located + tested)

> **Correction of an earlier draft of this section.** `ceaa-05xx_com_vE_250325.bin` is
> the **05-series** image: its RTC calendar is at **`0x2000a718`** (day@`+3`), *not*
> the 07-series `0x2000d850`, and the day byte is a **constant-base literal**, not a
> register-held pointer. My first rollover attempt poked `0x2000d850` (the wrong
> image's calendar) and so saw nothing — that was the mistake, not a harness limit.

The daily-reset detector is **`sub_08037cb2`**. Gated on flag `0x2000a758` bit 7
(and bit 12 clear), it compares the RTC calendar date `0x2000a718` (day`+3` /
month`+4` / year`+5`) against a **stored last-reset date `0x2000a720`**; on any
day/month/year change it `memset()`s the 24-byte daily block (`0x20009976` =
energy-base `+0x22`, i.e. IR 28-37) to 0 and copies the new date into the stored
slot — leaving the cumulative counters (IR 40-59) untouched. (A second, separately
dated reset path follows at `0x08037d2a`, driven by `sub_080379b8` writing the gate
`0x2000a7b0`; the test exercises just the calendar-date block by stopping at
`0x08037d2a`.)

Because the calendar is constant-base, the detector is **driveable in isolation**
(exactly like the accumulator): set the flag, set `0x2000a718`/`0x2000a720`, seed
the daily block, and call `0x08037cb2` — a day change zeroes the daily counters, a
same-day call keeps them. This is now a **common test asserted against both
images** (§5), not a harness gap.

## 5. Our reimplementation + tests

[`include/inv/energy.h`](../include/inv/energy.h),
[`src/energy/energy.c`](../src/energy/energy.c) reproduce the mechanism faithfully:
the same half-rate integration, the `3,600,001` threshold / `3,600,000` step, and
the `op_state >= 3` gate. `energy_tick()` accumulates, `energy_rollover(rtc_day)`
zeroes the daily counters on a day change (cumulative persists),
`energy_publish()` exposes the counters to IR 28-37 / 40-59, and `energy_reset_all()`
serves HR 11 `EnergyRecordClr`. Wired into the 1 Hz path in
[`src/main.c`](../src/main.c), fed by the instantaneous power input registers.

Tests:
- **Common accumulation (factory + ours)** [`tests/test_energy.py`](../tests/test_energy.py)
  + [`energy_contract.py`](../tests/energy_contract.py): the SAME `ENERGY_VECTORS`
  (counts/tick, sub-threshold cadence, gating) drive the factory accumulator
  `0x0801fbc4` and our `energy_tick()`; both agree.
- **Common daily rollover (factory + ours):** the SAME `ROLLOVER_VECTORS`
  (new day / same day / month boundary) drive the factory calendar-date detector
  `0x08037cb2` and our `energy_rollover()`; both zero the daily counter (IR 28) on
  a day change and keep the cumulative counter (IR 40), and both keep the daily
  counter when the day is unchanged.
- **Host** [`tests/test_energy.c`](../tests/test_energy.c) (`make test`): the
  accumulation, publish, rollover and reset in isolation, toolchain-free.

## Confidence

- **Proven:** struct base + register offsets (marker probe); the accumulator
  mechanism, the Epv1 path (fn `0x0801fbc4`, power `STATUS+0x28`, sub `+0xaa`,
  threshold/step), and the state gate — validated dynamically. The **daily
  calendar-date reset** (fn `0x08037cb2`, calendar `0x2000a718` vs stored
  `0x2000a720`, daily block `0x20009976`) — validated dynamically and asserted
  against both images.
- **Not calibrated:** the physical units (power scale, real tick rate) behind the
  `>>1` and `3.6M` constants — reproduced from the factory arithmetic, not derived
  from first principles.
- **Not separately modelled:** the factory's *second* daily-reset path
  (`0x08037d2a`, gate `0x2000a7b0` via `sub_080379b8`) — a belt-and-suspenders
  reset with its own date source; our firmware's single `energy_rollover()` covers
  the behaviour the registers expose.
