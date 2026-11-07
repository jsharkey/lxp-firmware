# Power-path relays — what drives them, and register-based names

> **Authoritative wiring:** the relay pin/role summary is in the [wiring overview](wiring/README.md#local-gpio-not-inter-processor-links). This doc remains the full relay-drive analysis. (Note the IR_STATE address correction: authoritative is `0x2000a0d8+0x90`.)

Status: **recovered by static + dynamic RE of the `ceaa-07xx` ARM image.** Each
relay's GPIO driver, the exact RAM fields/bits that gate it, and the one solidly
register-anchored input (**IR_STATE**, input register 0) are proven; the
physical silkscreen identity of each contactor is **reasoned from the gating +
the influencing registers** and flagged by confidence. Builds on the pin map in
[`docs/16`](16-arm-io-map.md).

The six power-path relay pins from docs/16 are driven by four logic functions:

| Relay pin | GPIO driver | Logic (per-loop) function |
|---|---|---|
| **PA12**, **PB3** | `sub_080334fc`, `sub_08033536` | `sub_08018a7c` — AC transfer pair |
| **PB2**, **PC6** | `sub_080334ae` (sel 1 / 2) | `sub_08016ec6` — state/run gating |
| **PC5** | `sub_0803348e` | `sub_08017022` — slow, state-change gated |
| **PD11** | `sub_08033556` | `sub_08035ef2` — single grid-status bit |

## The shared machinery (proven)

> **RE-CORRECTION (T02b, verified statically + executed; supersedes the note that
> stood here).** An earlier "correction" in this spot was itself an artifact of a
> disassembler base off by `0x5000` (see [`docs/19`](19-gpio-test-harness.md) §T02)
> and got the addresses backwards. The verified facts for `ceaa-07xx_vE_260214`
> (`reference/ceaa-07xx_vE_260214.bin`):
> - The telemetry bank **is `0x2000ce5c`** (22 literal refs); `0x20009e54` is the
>   one with **zero** refs (docs/22, docs/33).
> - **IR_STATE is the byte at `0x2000d0e4 + 0xa0`** — confirmed because the PC6/PB2
>   relay decider `sub_08016ec6` reads exactly `[0x2000d0e4+0xa0]` to gate PC6.
> - The classifier/state-machine is **`sub_0801a678`** (not `sub_0801b480`, which
>   is a periodic housekeeping/RTC-tick task — docs/22). `sub_0801a678` reads the
>   bank's fault (`+0xd0`) and warn (`+0xd4`), composes them into
>   `state+0x98` (fault word) / `state+0x9c` (warn word), and writes IR_STATE
>   (`+0xa0`) from the received mode byte. Feeding a USART2 mode byte on the wire
>   (T02a) now drives IR_STATE end to end (verified).
>
> **PC6 gate (`sub_08016ec6`, selector 2):** `PC6 = (IR_STATE >= 3)` on the clean
> path — closed in a running mode, open in standby/fault/programming — **except**
> it *blinks* when there is no fault (`state+0x98 == 0`) **and** a warning is
> present (`state+0x9c != 0`); a manual override (`0x2000da6c` bit 4) forces it.
> The blink path (`0x08016f7e`) toggles PC6 on a counter and does **not** read
> IR_STATE, so while a warning is present PC6 blinks regardless of mode. The two
> warnings that stand in a bare harness are both now cleared from the wire/GPIO:
> **W008** (FW-version mismatch) clears when `bank+3..6` = "ceaa" (fed in a tag-0
> frame; `sub_0801a93a`), and **W006** (comms health) clears when the **PD8 "detect"
> input** is high (GPIOD bit 8, read by `sub_0801ac2c`, docs/16) and `bank+0xca`
> bit 0 is clear. With both cleared (`state+0x9c == 0`) the decider's clean path runs
> and **PC6 cleanly follows the operating mode** fed on USART2 — demonstrated end to
> end by `test_usart2_mode_drives_pc6` (docs/39 T02b). (Programming mode, IR_STATE==2,
> is a deliberate blink.) So PC6 is a whole-inverter run-enable relay, but its inputs
> are now all pinned and drivable in the harness — it *is* a function of the mode once
> the inverter is made healthy.

**1. The operating mode = IR_STATE (input register 0).** The resolver
`sub_0801a678` reads the DSP telemetry struct `0x2000ce5c` (bytes `[0]`/`[1]` =
the DSP's working-state) and writes a mode byte to **`0x2000d0e4 + 0xa0`** plus
two extended-status dwords at **`+0x98` / `+0x9c`**. The byte values it writes —
`0x01, 0x02, 0x04, 0x08, 0x14, 0x80, 0x88, 0xC0, …` — match
[`include/inv/states.h`](../include/inv/states.h) / Modbus **IR_STATE (reg 0)**
*exactly* (`0x04`=PV on-grid, `0x40`=battery off-grid/EPS, `0x80`=PV off-grid,
`0xC0`=PV+bat off-grid, …). So **`0x2000d0e4+0xa0` is the live operating-mode
bitmask (IR_STATE)**, and the relays that test it are gated by the inverter's
working mode.

**2. The grid/EPS/fault status comes from the DSP.** `0x2000ce5c` is written by
the comms-cluster parsers (`sub_0800e60a`, `sub_080243c0`, `sub_08025ab8`,
`sub_0802677a`) — i.e. it is the **DSP-link telemetry struct**. Its status dwords
(`+0xb8`, `+0xbc`, `+0xc4`, `+0xca`, `+0xd0`, `+0xd4`) are the grid-qualified /
EPS / fault bits the ARM relays react to; these are the same quantities the ARM
re-publishes as the grid/EPS input registers (IR 12–27).

**3. A manual/AutoTest override.** The relays have a bypass path: when the
manual-mode flag **`0x2000d0e4+0xa9`** is set, they are driven directly from a
relay-command word **`0x2000da6c`** (PB3←bit0, PA12←bit1, PB2/PC6←bit4) instead
of the normal logic. Both the flag and the command word are written by
`sub_0801f596` — the **grid-protection self-test / manual relay path** (cf.
`IR_AUTOTEST`, reg 71), which must open/close the AC contactors on command.

## Relay-by-relay

### PA12 + PB3 — AC transfer pair (`sub_08018a7c`)

Driven **together**, which is the signature of the grid/EPS transfer switch.

- **Normal path** gates on the DSP grid status: `0x2000ce5c+0xbc` **bit 20**
  (grid-qualified) and its **bits 29-30** (a 2-bit grid/line state, `==2`
  blocks), plus `0x2000ce5c+0xca` bit 4 and `0x2000d808+8` bit 4, all behind a
  **~50-iteration debounce** (`0x2000dba4/5/6`, cap `0x32`). When the grid is
  fully qualified → `PA12` opens and `PB3` closes; otherwise the inverse. A
  config/enable gate at `0x2000d9ca` bits 1/3 can force both off.
- **Manual path** (`+0xa9==1`): `PB3`←`0x2000da6c` bit0, `PA12`←bit1.
- **Name:** **AC transfer contactors — grid/line relay + EPS (backup-output)
  relay.** Best reading: `PB3` = grid/line (closes when grid qualified), `PA12` =
  EPS/off-grid output (opens when on-grid) — polarity needs a bench check.
- **Influencing registers:** `IR_STATE` (0); grid metering `IR_VAC_R/S/T`
  (12-14), `IR_FAC` (15); **`HR_LINE_MODE` (146** APL/UPS/GEN), **`HR_CONNECT_TIME`
  (23** — the grid-connect wait the ~50-tick debounce implements), **`IR_AC_INPUT_TYPE`
  (77** grid vs generator), **`HR_FUNC_EN` (21** — EPS / anti-island bits).
- **Confidence:** high that this is the grid/EPS transfer pair; medium on the
  exact pin→(grid vs EPS) assignment.

### PB2 + PC6 — run-enable / bypass (`sub_08016ec6`)

- `PC6` (selector 2) gates on **`IR_STATE`** (`0x2000d0e4+0xa0`): it branches on
  mode `== 2` (PROGRAMMING) and on mode `< 3` (STANDBY/FAULT/PROGRAMMING) vs
  `≥ 3` (an actual running state), combined with the extended-status flags
  `+0x98`/`+0x9c`, behind a ~101-tick debounce (`0x2000db7a`). `PB2` (selector 1)
  follows the `+0x98` "active" dword behind a ~51-tick debounce (`0x2000db79`).
- Override: `0x2000da6c` **bit 4** forces both on.
- **Name:** **inverter run-enable + bypass/secondary contactor** — relays that
  close once the unit leaves standby/fault and is actively running.
- **Influencing registers:** `IR_STATE` (0) above all; the extended-status bits
  mirror the DSP run/grid flags (IR 12-27).
- **Confidence:** high that these follow working mode; medium on "bypass" vs
  "inverter-enable" labelling.

> **Correction to [`docs/16`](16-arm-io-map.md).** docs/16 noted PC6 as tied to
> the *output-priority / AC-First* setting (reading `+0xa0 == 2` as "AC First").
> That is **wrong**: the gating value is **IR_STATE** (working mode, at
> `0x2000d0e4+0xa0` — see the RE-CORRECTION above and [`docs/22`](22-arm-dsp-core-split.md));
> `== 2` is `STATE_PROGRAMMING`, not AC-First. PC6 is gated by the **operating
> mode**, not `HR_OUTPUT_PRIO_CFG` (145). (This does not change docs/14's
> conclusion about the AC-First *time windows* ending in telemetry.)

### PC5 — slow, state-change gated (`sub_08017022`)

- Reacts to **changes** in the `IR_STATE` extended dword (`0x2000d0e4+0x98`,
  diffed against saved copies `0x2000d950`/`0x2000db7b`), gated by
  `0x2000cd5c+0x6c` bit 16, `0x2000d0e4+0x9c` bit 26, and finally
  `0x2000c85c+0x13` **bit 23**, behind a **long ~1501-iteration debounce**
  (`0x2000daae`). The long, deliberate debounce implies a relay that must switch
  slowly/rarely.
- **Name (reasoned):** a **slow AC relay — AC-couple or generator-input
  contactor**, or an anti-island reconnect relay. The generator/AC-couple reading
  fits the deliberate switching and the state-transition trigger.
- **Influencing registers:** `IR_STATE` (0); `IR_AC_INPUT_TYPE` (77 grid/gen) and
  the generator-charge HR block if gen-input; AC-couple HRs if AC-couple.
- **Confidence:** medium-low on the specific role.

### PD11 — single grid-status bit (`sub_08035ef2`)

- Gates on `0x2000ce5c+0xc4` **bit 1** (a DSP grid/EPS status bit) → sets working
  flags `0x2000d9c8` bit10 / `0x2000da3a` bit1, then drives `PD11` behind a
  ~250-iteration debounce (`0x2000daf4`, with 10/25-tick sub-thresholds).
- **Name (reasoned):** **EPS/backup or load-control relay** — or the user
  **dry-contact** (docs/16 narrowed the dry contact to PD11/PC5; its single-bit,
  debounced, independent drive matches a dry contact).
- **Influencing registers:** `IR_STATE` (0) and the EPS/grid status bits (IR
  20-27); if it is the dry contact, the HMI "Dry Control" setting.
- **Confidence:** low-medium.

## Authoritative summary

| Pin(s) | Function role (name) | Proven driver registers | Reasoned influencing registers |
|---|---|---|---|
| PB3 / PA12 | **Grid line + EPS transfer contactors** | `IR_STATE` (0) | `HR_LINE_MODE` (146), `HR_CONNECT_TIME` (23), `IR_AC_INPUT_TYPE` (77), `HR_FUNC_EN` (21), `IR_VAC*/IR_FAC` (12-15) |
| PC6 / PB2 | **Inverter run-enable / bypass** | `IR_STATE` (0) | grid/run status IR 12-27 |
| PC5 | **Slow AC relay (gen-input / AC-couple)** | `IR_STATE` (0) change-trigger | `IR_AC_INPUT_TYPE` (77), gen-charge / AC-couple HRs |
| PD11 | **EPS/backup or dry-contact relay** | DSP grid-status bit (`0x2000ce5c+0xc4` b1) | EPS IR 20-27; "Dry Control" HMI setting |

All six are overridden by the **AutoTest/manual** path (`0x2000d0e4+0xa9` +
`0x2000da6c`, written by `sub_0801f596`; `IR_AUTOTEST` reg 71).

## How to finish (settle the silkscreen names)

The remaining uncertainty is which physical contactor each pin wires to. Two
reproducible routes, both using the committed harness:
1. **Register-driven:** seed the DSP telemetry struct `0x2000ce5c` /
   `0x2000d0e4` to each `IR_STATE` and grid-status combination and run the four
   logic functions under Unicorn, watching which GPIO pin changes (as
   `tools/emu_acfirst.py` does for the window) — maps *state → relay* exactly.
2. **Bench:** on hardware, drive each `IR_STATE` / grid condition and read the
   relay GPIOs (or listen for the contactor) to fix the silkscreen mapping.

Tools used: `tools/disres.py` (resolving disassembler — dumps each logic
function's RAM fields), `tools/gpio_map.py`, `tools/periph_map.py`.

> **Executed finding (T14 attempt, 2026-11-07): route 1 is blocked by a relay-ENABLE
> gate that must be RE'd first.** Running the real relay task under the RTOS (T02) on
> `ceaa-07xx` and watching PA12/PB3: `sub_08018a7c` is reached every pass but **always
> branches to its disabled path** (`0x08018b96`, opens both) — `0x08018afc` (grid-eval)
> is *never* entered — so seeding the grid-qualified bits (`0x2000ce5c+0xbc`) does not
> switch the pair. The gate is the enable term `0x2000d9ca` bit3 (the one enable that
> is not also a grid disqualifier): it reads 0 and is **re-derived every scheduler pass
> by `sub_0801887c`** (5 stores to `0x2000d9ca`, via `ramxref`), so a poke is cleared
> within ~500k instructions. `sub_0801887c` in turn derives it from the config word
> **`0x2000d0e4+4` bit9** and the DSP grid state. So the register-driven *state→relay*
> map (and the transfer **sequencing**: the three independent 50-tick debounces
> `0x2000dba4`/`5`/`6` in `sub_08018a7c`) cannot be oracled until `sub_0801887c` is
> decoded and its enable inputs are driven. **Next step (roadmap T14a):** RE
> `sub_0801887c` — pin which `HR_FUNC_EN` (21) / `HR_LINE_MODE` (146) / operating-state
> / grid combination sets `0x2000d9ca` bit3, drive it to *enable* the pair, then resume
> route 1. PC5/PD11 likely gate on `0x2000d9ca` bits 1/3 the same way — check together.
> (The **manual/AutoTest override** path of `sub_08018a7c` — `+0xa9==1` →
> PB3←`0x2000da6c` bit0, PA12←bit1 — needs no enable and is already the contract we
> mirror; it is the *normal*-path transfer that is gated.)
