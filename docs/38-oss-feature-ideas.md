# 38 — Feature brainstorm: what the open firmware could do beyond the factory

**Status: brainstorm / design notes. Nothing here is implemented, and nothing
here is a finding.** This doc lists features the open ARM "com" firmware could
add **on top of** the factory behaviour, now that the corpus maps most of the
inputs and outputs the com core can reach. Each idea says what evidence it
depends on and labels that evidence with the corpus's usual markers: **✔**
proven elsewhere in the tree, **~** inferred, **?** open. An idea is only as
solid as the weakest fact it needs. Where that fact is open, the idea names the
experiment that would settle it.

The trigger was the question "could we publish more internal sensor data to Home
Assistant (HA), and could HA get raw controls such as direct Smart Port
switching?" Both are covered (§3, §4), along with integration plumbing (§5),
diagnostics (§6) and the factory quirks we could fix (§7).

Factory feature baseline: the EG4 12000XP user manual (its private summary lives
in the factory-artifacts repo; facts used here are restated in our own words)
plus [`docs/11`](11-12000xp-revisions.md) for what the 07-series added.

---

## 1. Ground rules for any "beyond factory" feature

1. **A superset, flagged.** Everything new lives in a clearly separate register
   window (§2), with its own settings store, so the factory-compatible surface
   (`docs/wiring/ARM-UART5-dongle/`) stays byte-for-byte what the factory serves. A client
   written for the factory must not be able to tell the difference unless it
   reads the new window. No harness oracle exists for these features, so their
   tests are ours alone. Mark them that way (cf. `test_arm_sim_self_only.py`).
   **Every feature is also off by default behind its own feature flag**: the
   HR 10000–10007 enable mask. With the flags clear, the firmware is the factory
   mirror and passes every parity test unchanged. The mechanism, the feature
   classes and the test rules are in [`docs/45`](45-oss-feature-flags.md).
2. **Round-trip safe.** New settings persist only in the OSS flash region
   (`0x010000–0x03FFFF`, `LXP1` / `0x5A` records, [`docs/24`](24-oss-settings-region.md)).
   That way a flash-back to factory ignores them, and re-flashing ours restores
   them.
3. **The ARM is not the protection layer, so it must not try to be one.** Real-time
   power protection runs on the DSP, and the safety CPU votes and gates the
   inverter ([`docs/wiring/`](wiring/README.md), [`docs/29`](29-safety-cpu.md)).
   No feature may feed the DSP a value outside the ranges the factory HMI
   accepts, or touch the safety CPU's veto. "Raw control" here means **commanding
   within the envelope**, not widening it.
4. **Remote control is a lease, not a latch.** Every externally commanded state
   (force smart-port on, force grid charge, fan override, …) carries a
   time-to-live. It reverts to the configured automatic behaviour when the lease
   expires, when the commanding link goes quiet, or on reboot. A crashed HA
   instance must never leave the house running a stale override.
5. **Volatile overrides vs persisted settings.** HA-style automations write often
   (every minute or every price tick). The factory persists settings writes to the
   journaled SPI-NOR store ([`docs/21`](21-arm-config-flash.md)), so treating
   automation writes as settings would wear the flash for nothing. New control
   registers should be **RAM-only overrides** layered on the persisted setting,
   with the setting itself still writable the factory way.
6. **Factory quirks are decisions, not bugs to fix silently.** See §7 and
   [`docs/31`](31-factory-quirks.md).

---

## 2. Where the new data/controls live — an OSS register window

> **Superseded by [`docs/45`](45-oss-feature-flags.md) (feature flags) and the
> authoritative allocation in [`wiring/ARM-UART5-dongle/registers.md`](wiring/ARM-UART5-dongle/registers.md)
> ("Address-space allocation").** This section first proposed **IR/HR 1000–1399**.
> That was moved to **IR/HR 10000–10999**, because the factory's own space is
> still growing: it serves beyond-spec IR up to 204 live, the dongle polls to
> IR 380, and the factory read path reserves 4095–4999 and the battery bank from
> 5000. 1000 left too little room. Every OSS feature is also **opt-in behind a
> feature flag** (HR 10000–10007), so that with the defaults our firmware stays the
> factory mirror. Question 1 of §9 is answered: the factory reads `0` across the
> window and refuses writes with exception 2 (docs/45 §2.2).

The window is cut into 40-register blocks aligned to the dongle-spec query groups
(10000 = 250 × 40), so every block fits one legal query. **Block *k* sits at
10000 + 40·k in both spaces.** Block 0 is the control plane (discovery +
feature-enable mask). The remaining blocks are assigned per feature by the
docs/45 registry. The content groups this brainstorm suggested map onto that
registry as follows (numbers per docs/45 §3.2, all still ⬜ proposals):

| content (§ref) | docs/45 feature ID → block(s) |
|---|---|
| **identity & capability**: OSS magic, schema version, feature bitmap (§3.1) | control plane, block 0 (always on) |
| git hash, build date, uptime, reset reason (§3.1, §6) | ID 1 → block 1 |
| **bug-report recorder** status + register-window read cursor (§6.1) | ID 2 → block 2 |
| **live I/O state**: relay bitmap, fan duties, buzzer/LED/backlight, lease status (§3.2) | ID 3 → block 3 |
| **derived & high-resolution electrical** (§3.4) | ID 4 → block 4 |
| **windowed stats** (§3.5) | ID 5 → block 5 |
| **link health** (§3.6) | ID 6 → block 6 |
| **battery detail**: per-pack + cell min/max/Δ + temps + alarm bits (§3.3) | ID 7 → blocks 7–9 |
| **cross-check view** (§3.7) | ID 8 → block 10 |
| **event journal** / fault history (§3.8) | ID 9 → block 11 |

HR side: each feature's persisted settings (OSS region) and **volatile
lease-based commands** (§4) sit in the HR half of its own block. One
self-describing **schema table**, which a client can read register by register as
`{id, name-hash/index, unit, scale, signedness}`, would let an HA/ESPHome
integration generate entities without hand-maintained YAML (§5.3). It fits as a
later control-plane or block-1 addition.

---

## 3. Surfacing more internal data (input-register ideas)

### 3.1 Identity / capability block — *easy, no RE needed*
Firmware identity (OSS magic, version, git hash), variant (`ceaa`/`FAAB`/`ccaa`,
already in `variant.h` ✔), feature bitmap, uptime, reset reason (IWDG vs power-on
vs software, from the RCC reset flags), and the CPU versions we already track
(HR 9/10, [`docs/32`](32-firmware-version-registers.md)). Clients can then gate
features on what the firmware actually supports.

### 3.2 Real relay / actuator state — *easy; pins ✔, roles ~*
Publish a bitmap of the **actual output levels** of the six power-path relay
pins (PA12, PB3, PB2, PC6, PC5, PD11, ✔ pins, [`docs/18`](18-power-path-relays.md)),
plus whether the manual/AutoTest override (`0x2000da6c`-equivalent) is active, plus
fan PWM duties (TIM1 CH1–4 on PE9/11/13/14, ✔ AF) and buzzer state (PC7, ~). The
factory never exposes relay state on Modbus. HA would see a grid-loss transfer as
a relay edge rather than inferring it from IR 0. The **semantic** name of each bit
stays ~ until the silkscreen mapping is pinned. Publish by pin first and name the
bits once roles are proven.

### 3.3 Battery detail the inverter already receives but drops — *medium; frames ✔, layouts partly ?*
The ARM receives and buffers far more than it publishes ([`docs/34` §2](34-multi-battery-can.md)):

- `0x311–0x321` **per-pack** telemetry and `0x370–0x381` **stack detail**: min/max
  cell V and T, module counts, capacity, version, serial. ✔ frames received, ✔ no
  register publishes them. Byte layouts are **partly ?**: `0x373` cell detail was
  injected with realistic values, but the full table-driven builder is not
  byte-mapped.
- `0x35A` second alarm/protection set: received and staged, never published ✔ (Q3).
- `0x35E` manufacturer string and `0x35F` firmware/capacity ✔ frames.

Features this enables in HA: per-pack SOC/SOH/V/I, **cell imbalance Δ** (max − min
cell V) as a battery-health sensor, hottest-cell temperature, per-pack firmware
versions (spotting a pack left behind after a remote BMS update), and real BMS
alarm bits. The extension could also **feed the existing IR 5000–5126 bank** from
`0x3xx` frames, so tools that already poll it (the dongle does, live, `docs/34` §2d)
light up on EG4-LL stacks. That needs a decision, because it changes a
factory-defined range's behaviour (§7).

Open first step: byte-map `0x311–0x321` / `0x370–0x381` from `FUN_0002a0bc`
(`tools/batt_canmap.py --builders`) or from a live CAN capture.

### 3.4 Derived and higher-resolution quantities — *easy; ARM-computed*
Everything here is arithmetic on values the ARM already holds:

- **Signed battery current and power**: one register, + charge / − discharge,
  instead of the IR 10/11 pair.
- **Per-string PV current** `Ipv ≈ Ppv / Vpv`. The EG4 map has no Ipv register
  ([`docs/13`](13-mppt-controller.md)), so this is useful for spotting a shaded or
  failed string.
- **Energy at Wh resolution, 32-bit.** The factory counters are 0.1 kWh
  ([`docs/37`](37-energy-accumulation.md)). The accumulator already integrates
  finer than that internally (~), so HA's energy dashboard gets smooth data
  instead of 100 Wh steps.
- **Smart-port / EPS-port / grid-side power split.** The 07-series HMI added
  `Psmart:` / `Peps_port:` / `Pgrid_side:` ✔ strings ([`docs/11`](11-12000xp-revisions.md)),
  but whether they reach any IR is **?**. Find the getter behind those HMI fields
  and export it.
- **Battery energy remaining (kWh), time-to-empty, time-to-full**, from SOC ×
  capacity (IR 97 once Q2 is fixed, or HR 147) and the current battery power.
- **Unix-epoch timestamp** register (RTC ✔, [`docs/36`](36-rtc-calendar-and-energy-rollover.md))
  so a client can timestamp a poll without trusting its own clock.

### 3.5 Windowed statistics — *easy; ARM-local*
At a 10 s poll, HA misses a 2 s surge. The ARM sees every telemetry frame, so it
can keep **min/max/mean since the last read** (or over a fixed rolling window) for
load power, battery voltage, battery current and PV power. Peak-load and sag
values are what you need to size a generator or understand an overload trip
(W028). An event counter for transfers (grid→battery and back) and the duration
of the last outage come almost free from the relay-edge tracking in §3.2.

### 3.6 Link-health counters — *easy; mechanisms ✔*
Per link (USART2 safety CPU, USART3 DSP, CAN1 BMS, UART5 dongle): good frames,
CRC errors, timeouts, last-seen age. The factory already keeps USART2 fail counters
(`0x20009048[6]`, feeding the comms-loss/E017 logic ✔, [`docs/33`](33-usart2-telemetry-bank.md)).
They are just never exported. In HA this becomes "BMS link flapping" long before it
becomes W000.

### 3.7 Safety-CPU vs DSP cross-check view — *medium*
The ARM receives **two independent measurement streams**. One is the safety
CPU's own grid/PV samples on USART2, which feed the factory registers ✔. The other
is the DSP's `0x49` telemetry on USART3 ✔ ([`ARM-USART3-DSP/telemetry-0x49`](wiring/ARM-USART3-DSP/telemetry-0x49.md)).
Publishing both, plus the delta, gives a live "do the two measuring processors
agree?" diagnostic, which is the quantity behind E027. Also expose the DSP's raw
working-state byte next to the classified IR 0. The manual's engineering fields
(`NextStatus`, `ExitReason1/2`, `Run_Trace`) are natural companions once
located (?).

Related: the USART2 bank has a dense block of **parsed but unpublished** fields
(`+0x13…+0xc0`, an extended region past `+0x100`, ✔ unpublished, semantics ?,
[`docs/33` §2](33-usart2-telemetry-bank.md)). A first step that costs nothing
analytically is a **raw "debug window"** that mirrors those words as-is. Then
correlate them against known conditions on a live unit and promote the ones
that get named.

### 3.8 Timestamped fault/event history — *medium*
The LCD's Notice → Record tab keeps fault/alarm history with time and date
(manual). Expose it over Modbus as a cursor plus entries `{epoch, code, set/clear}`,
and add an OSS event journal (relay transfers, lease grants and expiries,
settings changes and who made them) in the OSS flash region. HA gets a precise
"what happened at 03:12" without having polled at 03:12. Size it within the
192 KB OSS region (§6.3).

### 3.9 Not possible without new hardware
The com MCU has **no analog inputs configured** ✔ ([`docs/16`](16-arm-io-map.md)).
New physical sensors (an extra CT, ambient temperature) can only arrive over a
spare serial port (§5.2) or the PB6/PB7 bit-banged bus (~ temp sensor / share
line, not pinned). Per-string currents or MPPT internals reach the ARM only if the
DSP relays them on `0x49`. The ARM has no MPPT wire ✔ ([`docs/13`](13-mppt-controller.md)).

---

## 4. Raw-ish controls (holding-register ideas)

Every command in this section follows §1.4 (lease + revert) and §1.5 (volatile).
The proposed generic shape is a **command block** of
`{mode, value, lease_seconds, sequence}` per controllable thing. The firmware
echoes `remaining_lease` and `active_source` (HMI / dongle / OSS port) in the IR
mirror (§3.2).

### 4.1 Direct Smart Port control — *high value; gated on one open fact*
Factory behaviour (manual): the Smart Port is **either** a Smart Load output
**or** an AC-couple input. The two are mutually exclusive, and wiring both
damages the unit. Smart Load turns on when PV power is above a start threshold
and SOC/voltage is above its start value, and off below the end value. AC-couple
engages below SOC/voltage thresholds after about a 5-minute delay.

Proposed OSS modes for the **Smart Load** role:

| mode | behaviour |
|---|---|
| `auto` | factory threshold logic (default; unchanged) |
| `force_on` (lease) | port on regardless of PV/SOC, still subject to the hard guards below |
| `force_off` (lease) | port off regardless of thresholds |
| `external` | port follows an HA-written boolean, with lease; on expiry → `auto` |

The guards must hold in every mode: never energise in the **AC-couple** role
(refuse the command; the role itself changes only in standby, as the factory
requires); honour E012 (smart-load short) and any DSP/safety-CPU trip; a
**minimum on/off dwell** (for example 30 s) so automations cannot chatter a
contactor; and an optional **SOC floor** below which `force_on` is dropped. That
keeps the battery reserve for the EPS loads.

**The open fact (?): what physically switches the Smart Port.** If its contactor
is an ARM GPIO, this is easy: PC5 (slow, gen/AC-couple-like) and PD11 are the
unnamed candidates ([`docs/18`](18-power-path-relays.md)), and the factory already
has a manual relay-override path. If the switching decision is DSP-side, the
feature needs the Smart Load fields in a config block, and the HMI's
`fn_Smart_Load` writes into the block-push source struct `0x20009854` ✔
([`docs/08`](08-arm-dsp-config-protocol.md)), which hints at a DSP-side role.
**Decisive experiment** (harness, same technique as `tools/emu_acfirst.py`): set
Smart Load enable plus thresholds, sweep SOC/PV through the start and end values,
and watch (a) which GPIO toggles and (b) which DSP-push bytes move. One run
answers it.

AC-couple role, analogous: `force_couple_off` (lease) for an HA "don't AC-couple
right now" decision, such as negative export prices on the grid-tie side.

### 4.2 Generator / dry-contact control — *medium; pin ~*
Direct start/stop with a lease, an **exercise schedule** (run 15 min weekly
under load), and HA-driven start on a forecast deficit. The 07-series added
warm-up/cool-down and quick-start ✔ strings ([`docs/11`](11-12000xp-revisions.md)),
and the OSS command should go through that same sequencing, never around it.
The dry-contact pin is PD11 (leading ~) or PC5 ([`docs/16`](16-arm-io-map.md)
"Dry Control"). A **generic spare dry contact** mode ("HA-owned relay") would
also enable SOC-staged load shedding, an external "grid down" signal and similar
uses, provided that contact is not wired to the generator.

### 4.3 Dynamic charge/discharge setpoints — *medium; push path ✔, field names ~*
HA tariff/solar-forecast automations want to say "charge at ≤ 40 A from grid
until 06:00" or "cap discharge to 3 kW now". The ARM pushes the configured
battery limit set in **block 1** ✔ (field roles medium/low,
[`ARM-USART3-DSP/block-01`](wiring/ARM-USART3-DSP/block-01.md)), and the DSP takes min(configured,
live BMS). That makes the push a natural **clamp-only** knob: an OSS override can
lower limits but never raise them above the persisted setting or the BMS value.
The same pattern covers AC-charge power/SOC targets (HR 64-89 family) and Max Grid
In Power (07-series ✔ string) for **peak shaving**. All of it should be volatile
overrides (§1.5).

### 4.4 A real scheduler — *medium; partly built*
- **Turn on the dormant half-hour table** (HR 126-131, Q5) as an opt-in OSS mode.
  `optchg_slot_mode()` already exists and is tested ([`docs/31` Q5](31-factory-quirks.md)).
  HA writes tomorrow's 48-slot charge/discharge plan from day-ahead prices once a
  day, and that one write is a whole tariff integration. It needs a precedence
  rule against the AC-charge / AC-First windows (HR 68-73, 152-157), which are
  evaluated ARM-side ✔ ([`ARM-USART3-DSP/clock`](wiring/ARM-USART3-DSP/clock.md)).
- More than 3 windows, weekday/weekend sets, and seasonal profiles, all ARM-side
  because window evaluation already lives on the ARM.
- **Profiles**: named settings bundles ("summer", "winter", "away", "storm")
  switched by one register. *Storm prep*: grid-charge to 100 % now, raise the
  reserve SOC, hold until a lease expires.

### 4.5 Battery-care modes — *medium; depends on §3.3*
- **Storage mode** while away: hold SOC in a band (for example 40–60 %) using the
  clamp knobs in §4.3.
- **Periodic full charge** for BMS SOC recalibration (weekly to 100 % plus an
  absorption hold).
- **Imbalance-aware absorption**: extend the top-of-charge hold while cell Δ
  (§3.3) exceeds a threshold, within the BMS-advertised limits.
- Lead-acid **equalization scheduling** (HR 149-151 exist in the spec, `idx`).

### 4.6 Thermal / acoustic control — *easy-medium; fully ARM-local*
The fans are ARM TIM1 PWM ✔ (AF), and the factory exposes only slope/max per fan
(manual). The ARM could offer a **temperature curve** (T1/T2, radiator temps ✔ IR
65/66) with a **quiet-hours** ceiling, and pre-cooling ahead of a scheduled
high-power charge. Hard rule: the OSS curve may only ever **add** airflow above
the factory curve once any temperature nears the warning thresholds (manual:
~87 °C / ~90 °C warn). W009 "fan stuck" implies tach feedback somewhere (?, maybe
among the unread inputs PE8/10/12/15). If it is found, publish RPM.

### 4.7 Human-interface niceties — *easy; ARM-local, LCD driver ✔*
- **Buzzer**: quiet hours, mute-until, an HA-triggered "locate" chirp. The buzzer
  is PC7 TIM3 PWM (~).
- **LCD**: an "HA page" whose few text lines HA writes over Modbus (price,
  forecast, message). Backlight schedule (PD14/PD15 candidates ~). Our own
  renderer already draws on the real panel ✔ ([`docs/28`](28-factory-hmi.md)).
- **Status LED** patterns for OSS states (lease active, OSS firmware running) —
  but the real expressive surface is the **front-panel RGB ring** (§4.8).
- A front-panel **"remote control allowed"** toggle (§5.4).

### 4.8 Front-panel RGB LED ring — the expressive display — *easy; fully ARM-local, driver ✔*

The circular front "halo" is **25 individually-addressable full-24-bit-RGB LEDs**
on PD15 (TIM4-CH4 PWM + DMA), decoded in [`docs/40`](40-led-ring.md). The factory
uses it only for a green/amber/red spinning comet off `IR_STATE`; the hardware is a
general 25-pixel RGB ring we can drive however we like, and frame updates are cheap
(PWM-DMA, no CPU bit-bang). It even already contains an unused **rainbow** cycler
(mode 1). All inputs these ideas need (SOC on [IR 5](wiring/ARM-UART5-dongle/IR005-SOC_SOH.md),
PV power on the `PPV*` input regs, state/faults) are already in the register image,
so this is pure ARM-local output — one of the easiest high-delight features.

Building blocks (details and a reimpl sketch in `docs/40`):
- **Per-state palette** beyond green/amber/red: blue = AC-charging, cyan = PV-only,
  white = standby, purple = grid-export — a one-line change in the state→colour map.
- **Gauge / arc**: light `K = round(25·x)` LEDs as a filled arc — an **SOC dial**,
  load/power meter, or charge-progress bar. The single most useful upgrade.
- **Rainbow** (already implemented), **static rainbow ring** (`hue = 360°·led/25`),
  **breathe/pulse** idle glow, **blink/strobe** faults, **multi-comet**, and
  **spin-speed/direction by load** (faster under higher power, reverse on discharge).
- **Severity colour-fade**: continuous green→amber→red as a function of warning
  severity instead of three discrete modes.

**Signature design — "solar rain into a filling battery."** Split the ring into a
**top arc** (the sky) and a **bottom arc** (the battery):
- **Top — solar rain.** Spawn **yellow "sun-shower" drops** at the top that fall
  down the two sides of the ring (a lit pixel stepping LED-by-LED down each flank,
  fading as a short tail). The **spawn frequency tracks total PV generation** — a
  drizzle at a few hundred watts, a downpour near rated power — so the panel
  *visibly rains harder the more the sun is producing*. (PV watts from the `PPV1/2
  (+PPV3)` input regs, summed.)
- **Bottom — battery fill.** The bottom arc is an **SOC gauge**: fill LEDs from the
  lowest point up to `round(SOC% · bottom_count)`, coloured by a **red→amber→green
  gradient keyed to SOC** (red near empty, green near full; SOC from IR 5 low byte).
  As the rain falls into it, the battery arc rises and greens — an at-a-glance
  "PV charging the battery" story on the front panel.
- Nice touches: a drop that reaches the fill line gives a brief brighten/ripple;
  on discharge, reverse the motion (battery arc drains, a downward "draw" glow); on
  a fault, override to the red comet (don't hide alarms behind the pretty mode).
  This is a cosmetic OSS "mode" selectable via the HMI "LED Mode", never masking the
  fault/warning states (which must still win — §1 ground rules). Feasible today; the
  only open hardware point is confirming the blue channel / wire byte-order on a
  real unit (`docs/40`).

---

## 5. Integration plumbing (how HA actually gets at it)

### 5.1 The bus problem
UART5 is a **single-master RS-485 bus and the dongle is the master** ✔
([`docs/26`](26-dongle-firmware.md)). HA cannot share it as a second master.
Options, in order of least hardware change:

1. **Replace the dongle** with an RS-485 master that HA controls (USB-RS485 on the
   HA host, or an ESP32 running ESPHome/Modbus). This is the simplest path and
   loses the EG4 cloud.
2. **Keep the dongle and add a second slave port** for HA (§5.2).
3. **Transparent passthrough**: the dongle is a dumb frame relay ✔ (`docs/26`), so
   whatever path reaches it locally (?, not established in the corpus) also
   reaches the OSS window for free.

### 5.2 A second Modbus slave on a spare UART — *gated on peer identity*
UART4 (PC10/PC11, RS-485, 2400 baud, DE ~PA15) has an **unknown peer** ✔/?
([`wiring/ARM-UART4`](wiring/ARM-UART4-open.md)). USART1 is not even enabled ✔
([`wiring/ARM-USART1`](wiring/ARM-USART1-open.md)). If either is free on the board
(schematic/bench), it could host an HA-dedicated slave at a sane baud. **Caution**:
PA15 appears to be shared as the DE line for UART4 *and* UART5 (~), so driving
both as independent RS-485 slaves may be electrically impossible without a board
change. Settle that before promising the feature.

### 5.3 Speak standard Modbus RTU too — *easy-medium; high HA value*
The dongle framing is EG4-specific: a 10-byte SN after the function code and
**little-endian** registers ✔. HA's built-in Modbus integration and most
off-the-shelf masters cannot speak it. A **dual-framing slave** could accept plain
Modbus RTU (no SN, big-endian) next to the EG4 framing. The two frame shapes are
told apart by length and CRC position, and the firmware answers in the framing it
was asked in. Combined with the schema table (§2), a stock HA Modbus config or an
auto-generated ESPHome config can read the inverter with no custom component.
Needs care: no false positives on an EG4 frame that happens to CRC-match as a
standard one (add a mode setting: EG4-only / standard-only / auto).

### 5.4 Write authorization
RS-485 has no authentication, so the OSS window should be **read-only by
default**. Remote writes to the HR command block should need a front-panel
"Remote control: allow" setting (persisted, OSS region), optionally with a
write-unlock register (a PIN or rolling token) and an auto-relock timeout. Log
every remote write in the event journal (§3.8) with the link it arrived on.

### 5.5 Clock
HA can set time over HR 12-14 today ✔. An OSS **epoch + UTC-offset/DST rule**
register pair would let HA keep the RTC correct across DST without
rewriting windows. The factory's time-zone handling lives in the cloud (manual).

---

## 6. Diagnostics & maintenance features

### 6.1 Bug-report flight recorder — **HIGH PRIORITY (bring-up)**

**Why first.** When we first flash our firmware onto a real unit, the failures
we most need to see are the ones a dongle poll cannot catch: a relay that
chatters for 300 ms, a state that flickers through `FAULT` and back, a DSP frame
that arrives malformed once a minute, a fault bit that sets and clears between
two 1 s polls. A dongle poll also shows only the ~150 published registers, not
the internal state behind them. The recorder fixes both problems. It keeps a
**RAM-only ring** of high-resolution telemetry, state edges and raw link frames.
When something goes wrong it **keeps recording for a while, then freezes** the
ring. The dongle (or any master we control) then pulls the frozen capture out
over custom Modbus function codes, in the same spirit as the `0x21/0x22/0x23`
update gateway. It needs no new RE, takes no control action, and writes nothing
to flash. Everything it records is already passing through our own code.

#### Capture model

```
            armed (recording, oldest overwritten)          post-trigger         frozen
  ... ──────────────────────────────────────────┬──────────────────────────┬────────────── ...
                                              trigger              25 % of ring          until the
                                       (first event latches)    (or time cap) more     extractor
                                                                                       ACKs it
  ring after freeze:  [ ~75 % history before the trigger ][ ~25 % after it ]
```

1. **Armed.** Every record is appended to a single byte ring, overwriting the
   oldest record. Records are variable-length TLVs, so the ring holds whatever
   mix the active profile produces.
2. **Trigger.** The first qualifying event (below) latches: it writes a `TRIGGER`
   record, remembers its ring offset and starts the post-trigger budget.
3. **Post-trigger.** Recording continues until **25 % of the ring's capacity in
   bytes** has been written since the trigger. A **time cap** (default 30 s)
   also ends this phase, so a trigger on a quiet bus still freezes promptly.
   Further events in this phase are logged as `TRIGGER(secondary)` records but
   do **not** restart the window. They are often the most telling part ("the
   BMS link died 400 ms after the relay opened").
4. **Freeze.** Writes stop, and a one-shot **state snapshot** (below) is taken
   into a separate fixed area. The capture now waits for extraction. While
   frozen, new events are not recorded, but they are **counted and summarised**
   in a small list kept outside the ring (last 8 `{t, cause}` plus a missed-event
   counter). The extractor therefore knows what happened after the freeze, even
   though it doesn't have the detail.
5. **Re-arm** happens only when the extractor ACKs that capture's event id (see
   protocol). One event is held at a time, as intended: a burst of faults
   yields the first one in detail plus a count of the rest.

Writing 25 % *after* the trigger leaves ~75 % of history *before* it. Both the
ratio and the time cap are runtime settings (OSS HR block, volatile), so a
bring-up session can move them, for example to 50/50 to watch a recovery.

#### What gets recorded (record types)

All records start with `{u8 type, u8 len, u32 t_ms}`. `t_ms` is the SysTick
millisecond counter, so record times are exact relative to each other. The
capture header anchors them to the RTC.

| type | content | when written | typical size |
|---|---|---|---|
| `SAMPLE` | curated fast snapshot: IR 0 state, fault/warn words, Vbat, Ibat, SOC, PV V/P ×2, grid V/F, EPS V/F/P, bus V, temps, relay-pin bitmap, fan duties, link-health counters | fixed rate, default **10 Hz** (profile-selectable 1–50 Hz) | ~64 B |
| `EDGE` | one field changed: `{field id, old, new}` for IR 0, each fault/warn bit, each relay pin, link up/down, lease grant/expiry | **as it happens**, at full resolution, independent of the sample rate | 12 B |
| `RAW_U2` | safety-CPU frame on USART2 (the full bank frame, including the fields no register publishes, [`docs/33`](33-usart2-telemetry-bank.md)) | on receipt, **deduplicated**: skipped if byte-identical to the last one stored | ~90 B |
| `RAW_U3_RX` | DSP `0x49` telemetry frame | on receipt, dedup + per-block decimation | ~60 B |
| `RAW_U3_TX` | our outgoing DSP config block | only when the block's bytes **change** (the DSP acts only on changes anyway, [`ARM-USART3-DSP`](wiring/ARM-USART3-DSP/README.md)) | ~60 B |
| `RAW_CAN` | `{id, dlc, data[8]}`, including the extended frames no register publishes ([`docs/34`](34-multi-battery-can.md)) | on receipt, dedup per id | 14 B |
| `MB_WRITE` | every holding-register write: link (dongle/HMI/OSS), register, old → new value | as it happens | 14 B |
| `NOTE` | firmware self-report: assertion or invariant failed, parser rejected a frame (why), main-loop overrun, settings-validation reject | as it happens | ≤ 32 B |
| `TRIGGER` | cause code + detail, primary or secondary | at trigger | 16 B |

Deduplication is what makes this affordable. Most of the internal links repeat
the same frame many times a second, and the interesting content is the
*change*. The bounds are the wire rates: USART2 and USART3 are 19200 baud, so
each delivers at most ~1.9 KB/s raw even with no dedup at all.

**Profiles** pick what is recorded and at what rate, so the ring's time span
fits the bug. The profile is selected over Modbus or the HMI:

| profile | records | rough span in a 24 KB ring |
|---|---|---|
| `overview` (default) | `SAMPLE` @10 Hz + all `EDGE` / `MB_WRITE` / `NOTE` | ~35 s |
| `slow` | `SAMPLE` @1 Hz + edges | ~6 min |
| `dsp-deep` | edges + `RAW_U3_RX/TX` (dedup) + `SAMPLE` @2 Hz | link-dependent, ~10–30 s |
| `safety-deep` | edges + `RAW_U2` (dedup) + `SAMPLE` @2 Hz | ~10–30 s |
| `bms-deep` | edges + `RAW_CAN` (all ids) + `SAMPLE` @2 Hz | ~1–2 min |

(Spans are estimates from the record sizes above, not measurements. Measure
them on the bench and record the real numbers here.)

#### Triggers (each maskable)

- **Fault/warning rising edge**: any bit of IR 60–63 going 0→1. A per-bit mask
  lets a known-noisy warning be ignored.
- **State anomalies**: IR 0 entering fault, or a state transition not on an
  allowed-transition list, or more than N state changes in M seconds (chatter).
- **Relay anomalies**: a relay pin toggling more than N times in M seconds, or a
  relay pin disagreeing with what our relay logic expects for the current state.
- **Link anomalies**: link-loss timeout, a CRC-error burst, a frame the parser
  rejects, or a BMS CAN silence.
- **Firmware self-checks**: `NOTE`-class assertion failures, main-loop overrun
  past a budget, stack high-water crossing a guard.
- **Watchdog / fault reset**: see "surviving a reset" below.
- **Manual**: a Modbus command, or a front-panel key chord. When a user says
  "it's doing the weird thing *now*", one press freezes the last 30 s.

#### The freeze-time state snapshot

The snapshot is taken once, at freeze, into a fixed ~2 KB area outside the
ring. It holds the full IR and HR images (~0.8 KB), the raw safety bank (256 B),
the last raw frame of every link (even if dedup skipped it), the decoded
settings, per-link counters, the RCC reset flags, stack and loop-time high-water
marks, and the frozen-event summary. This captures internal state that is never
published as registers, at the moment that matters.

#### Surviving a reset (still RAM-only)

Put the ring, the snapshot and the control header in a **`.noinit` RAM
section** that the startup code does not zero, guarded by a magic value and a
CRC over the control header. SRAM keeps its contents across a watchdog or
software reset, but not across a power cycle. Our startup code chooses at boot:

- If the header is valid and a capture is **frozen**, keep it untouched and
  re-arm nothing until it is ACKed.
- If the header is valid and the capture was **armed or post-trigger**, and the
  reset flags say IWDG or software reset, **freeze it now** with
  `TRIGGER(cause=RESET, flags)`. The HardFault handler should also store the
  stacked PC/LR/xPSR and the fault-status registers into the control header
  before it resets. That turns "it rebooted" into the last seconds before the
  crash plus the faulting PC.
- Otherwise (power-on reset, or bad magic/CRC) initialise empty.

This costs no flash wear and no flash code. The one rule is that nothing else
may place variables in `.noinit`.

#### RAM budget

The MCU is assumed to have **64 KB SRAM** (`ldscripts/stm32f103ve.ld`, ✔ for the
-VE memory map. The exact part, possibly a GD32F303-class clone, is still open,
README). A rough static count of our current firmware from the source gives
~6–8 KB of buffers and state:

- config-slot images: 6 × 256 B
- IR/HR images: 160 + 256 regs
- per-pack bank
- three UART rings: 512 B each
- safety bank and frame buffers
- energy and HMI state

Add 2 KB stack and 1 KB heap from the linker script. *(Estimated from the source,
not measured: the ARM toolchain isn't installed here. Confirm with
`arm-none-eabi-size build/firmware.elf`.)* That leaves room for:

| region | default | note |
|---|---|---|
| ring | **24 KB** | compile-time `BUGREPORT_RING_KB`; 32 KB is plausible if the measured footprint allows |
| snapshot | 2 KB | fixed |
| control header + frozen-event summary | < 256 B | |
| **total** | **~26 KB** | keep **≥ 8 KB** headroom for growth, with a link-time assert |

CPU cost is a memcpy per record from main-loop context. The recorder must never
block, and it must never be called from an ISR: ISRs already hand bytes to the
main loop through ring buffers, and we record at parse time. One producer and a
frozen buffer that is read-only during extraction means no locks are needed.

#### Extraction — custom function codes on the dongle link (UART5)

Use the same EG4 envelope as the dongle traffic (`addr, func, SN[10], body,
CRC-16`), with **one new function code** from the Modbus "user-defined" range.
**`0x65`** is proposed: it is clear of `03/04/06/10`, of `0x21–0x23` and
`0x31–0x33` (update gateway, ✔ [`docs/13`](13-mppt-controller.md)), and of the
`0x41`/`0x49` SOF bytes used on the internal wire (different link, but best not
to invite confusion). The first body byte is a sub-command:

| sub | request | response |
|---|---|---|
| `0x00 STATUS` | — | state (armed / post-trigger / frozen), **event id** (u32, increments per capture), trigger cause + `t_ms` + RTC, capture length, CRC-32 of the linearised capture, frozen-event summary, profile, ring geometry |
| `0x01 READ` | event id, offset, length | that slice of the **linearised** capture (header, then snapshot, then records oldest-first). Refused if the event id doesn't match the frozen one, so a reader can never stitch together two captures |
| `0x02 ACK` | event id | re-arms. Ignored unless the id matches the frozen capture, so a stale or duplicate ACK cannot discard a newer capture |
| `0x03 TRIGGER` | cause note | manual trigger |
| `0x04 CONFIG` | profile, trigger mask, post-trigger %, time cap | volatile settings; gated by the write authorization of §5.4 |

- **Chunk size.** The default READ length is 80 B, the same payload as a
  40-register read, so it fits our existing `MB_FRAME_MAX` buffers and whatever
  the dongle's relay buffer is (? unknown). A larger chunk can be negotiated if
  both ends allow it. At 9600 baud 8N1 (~960 B/s), a 26 KB capture is ~30 s of
  back-to-back chunks. At the spec's 1 s minimum poll period, with one chunk per
  poll, it takes ~5–6 min. Either is fine for an event that is already frozen.
- **Self-describing capture.** The header carries a magic (`LXBR`), the format
  version, firmware git hash and variant, uptime and RTC at trigger, ring
  geometry, the trigger record's offset, and a record-type schema version. One
  header (`include/inv/bugreport.h`) is the single source for both the firmware
  and a host decoder (`tools/bugreport.py`, which would emit JSON/CSV plus a
  timeline plot).
- **Register-window fallback.** For masters that cannot send a custom function
  code (a stock HA Modbus integration, or a cloud path that filters function
  codes, ?), mirror STATUS in the recorder's OSS IR block (docs/45 feature ID 2 → block 2, IR 10080–10119, §2). READ then becomes
  a cursor: write the offset to an OSS HR and read 40 IR of data. It is slower,
  but any master can do it.

**Who does the periodic pull (?).** The stock EG4 dongle is a transparent pipe
for its cloud ([`docs/26`](26-dongle-firmware.md)), and nothing on it will poll
`0x65` on its own. Periodic extraction needs a master we control: custom
firmware on the ESP32-C3 dongle (poll STATUS every N s, drain on `frozen`, push
to HA/MQTT or a file), an HA-side RS-485 master (§5.1), or a laptop running
`tools/bugreport.py` on a USB-RS485 adapter during bench bring-up. The last one
is the minimum viable path. Also signal "capture waiting" locally (LCD icon,
status LED/ring pattern §4.8), so a user knows to pull it.

#### Factory coexistence and tests

- **?** How does the factory answer function `0x65`: an exception, silence, or
  the update gateway? Check it under the harness. A distinct answer doubles as
  "is OSS firmware running" detection for the extractor. This feature is
  ours-only, with no factory oracle.
- Host unit tests (`make test`) for the pure core: ring wrap with variable-length
  records, post-trigger budget arithmetic (bytes and time cap), freeze/ACK/event-id
  rules, dedup, linearisation, and `.noinit` header validation.
- Harness test (`make test-sim`, self-only): inject a fault bit through the
  safety-telemetry contract, keep running, then drive `0x65` STATUS, READ and
  ACK over the emulated UART5. Assert that the trigger record and pre/post
  windows are present and that ACK re-arms. Record it in each touched register's
  `## Test coverage`.
- Reads change nothing. The only state change is ACK or CONFIG, and the recorder
  never actuates anything, so it is safe to leave enabled in production builds.

### 6.2 Raw link taps
*Largely subsumed by the bug-report recorder (§6.1), which captures raw frames
with timestamps around an event. A free-running "last N frames" view is still
useful for RE when nothing has gone wrong.*

Keep a small ring of the last N raw frames per internal link (USART2, USART3,
CAN1) readable over the OSS window, gated by the same write-unlock. This is
priceless for the remaining RE (the `0x49` payload, unpublished bank fields,
per-pack CAN layouts), and it lets users with a stock dongle contribute captures
without a logic analyser.

### 6.3 High-resolution local logging
1-minute records of the core telemetry in flash, readable over Modbus (for
example func `0x14` read-file-record or a paged window), survive an HA outage.
**Space is the constraint:** the OSS region is 192 KB ([`docs/24`](24-oss-settings-region.md)),
about 2.5 days at 64 B/min. The factory's ~6.5 MB data-log ring
(`0x040000–0x68FFFF`) is far larger, but its layout is not decoded, and reusing it
would break factory round-trip of that history. That is an explicit decision to
take, not a default.

### 6.4 Self-test helpers (service mode only)
A guided relay click-test through the existing manual/AutoTest override path ✔,
while in **standby only** and behind the unlock. It helps pin the relay
silkscreen roles (the open item in [`docs/18`](18-power-path-relays.md)) on real
hardware and doubles as a user diagnostic.

### 6.5 Calibration gains — read-only
Blocks 2/7/8 push measurement **calibration gains** (Q10, unity `0x400`, ~
[`ARM-USART3-DSP/block-02`](wiring/ARM-USART3-DSP/block-02.md)). Exposing them **read-only** is
useful (spotting a mis-calibrated unit). Writing them is a factory-service
operation and should stay out of reach of normal remote control.

### 6.6 Firmware update of the com core itself
The 07-series bootloader + App split ✔ ([`docs/11`](11-12000xp-revisions.md)) and
the existing `0x21/0x22/0x23` update gateway ✔ ([`docs/13`](13-mppt-controller.md))
suggest an OSS-firmware update path over the same Modbus link. Whether it is safe
and clean-room-compatible depends on the (not ours) bootloader's protocol. Keep
the DSP/MPPT gateway behaviour unchanged.

---

## 7. Factory quirks we could fix (each is a recorded decision in `docs/31`)

| quirk | OSS opportunity | caution |
|---|---|---|
| **Q1** IR 101 carries high-res SOC, not max cell V | source IR 101 from `0x373` (§3.3) | changes a factory register's value; do it only if `0x373` layout is proven |
| **Q2** IR 97 = `"PN"` marker (20048 Ah) | publish real capacity from `0x379`/`0x35F` | same |
| **Q3** `0x35A` alarms never surface | publish in OSS window (non-breaking) | none — new registers only |
| **Q4** possible 10× current unit mismatch | publish a proven-unit signed current in the OSS window (§3.4); leave IR 98 alone | needs a live-bus reading first |
| **Q5** HR 126-131 table dormant | opt-in evaluator (§4.4) | define precedence vs AC-charge/AC-First windows |

Fixes that only **add** OSS registers (Q3, Q4) carry no compatibility risk. Fixes
that **change** a factory register (Q1, Q2) break the "factory client can't tell"
rule (§1.1), so each one sits behind **its own class-C feature flag**, default
off ([`docs/45`](45-oss-feature-flags.md) §3.2: ID 32 = Q1, ID 33 = Q2), with the
verdict recorded in `docs/31`.

---

## 8. Rough priority

| tier | features | why |
|---|---|---|
| **Bring-up — do first** | **bug-report flight recorder (6.1)**: RAM ring + post-trigger freeze + `0x65` extraction, with `tools/bugreport.py` on a USB-RS485 adapter as the first extractor | no new RE, no control actions, and it is the tool that makes debugging every other feature on real hardware possible |
| **Quick wins** (no new RE) | identity block (3.1), relay/actuator state (3.2), derived values (3.4), windowed stats (3.5), link health (3.6), Q3 alarms, raw debug window of unpublished USART2 fields (3.7), standard-Modbus framing (5.3), write authorization (5.4), **RGB LED-ring modes incl. SOC gauge + solar-rain (4.8)** | facts are ✔ and the data is already in RAM |
| **Next** (small RE or bench step) | Smart Port control (4.1, one harness run settles the switching path), generator/dry contact (4.2), clamp-only setpoint overrides (4.3), dormant-table scheduler (4.4), fan curve (4.6), LCD/buzzer niceties (4.7) | high HA value; each gated on one named experiment |
| **Research-gated** | per-pack/cell battery detail (3.3, CAN byte layouts), cross-check/engineering fields (3.7), second slave port (5.2, UART4/USART1 peer + PA15), local logging scale (6.3), OSS self-update (6.6) | depends on open items in `docs/34`, `docs/33`, `wiring/` |

## 9. Open questions this brainstorm adds

These go to the hand-off list. Each is a concrete experiment.

1. ✅ How does the factory answer IR/HR reads in the OSS window? **Answered** for the (moved) 10000+ window: reads `0`, writes exception 2 ([`docs/45`](45-oss-feature-flags.md) §2.2; UART5 pending T02).
2. Is the Smart Port switched by an ARM GPIO or by the DSP? (harness sweep, §4.1)
3. Which getter backs the 07-series `Psmart` / `Peps_port` / `Pgrid_side` HMI fields? (§3.4)
4. Is UART4 or USART1 free on the board, and is PA15 really a shared DE line? (schematic/bench, §5.2)
5. Where does fan tach feedback (W009) enter, if anywhere? (§4.6)
6. Byte layouts of `0x311–0x321` / `0x370–0x381`. (`docs/34` follow-up, §3.3)
7. How does the factory answer function `0x65` on UART5, and how large a frame does the stock dongle relay? (harness / bench, §6.1)
8. Measured RAM footprint of our build (`arm-none-eabi-size`), which sets the real recorder ring size. (§6.1)
