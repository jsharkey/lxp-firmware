# Does the ARM drive a GPIO relay from the "AC First" decision?

Status: **theory tested against the recovered evidence and found unsupported;
a dynamic cross-check probe is committed and pending the ARM image.**

## The question

[`docs/08`](08-arm-dsp-config-protocol.md) established that the **AC-First
load-priority windows** (Modbus regs **152-157**) are **not pushed to the DSP**.
The ARM evaluates them against its own RTC in `sub_0801eb4c`
(`start ≤ now < end`, start-inclusive/end-exclusive, with day-wrap) and produces
a derived "AC-First active now" status.

The open theory this document addresses: since the *mode* isn't sent to the DSP,
maybe the **ARM switches an AC/grid relay through a GPIO directly** when the
window goes active — i.e. the ARM, not the DSP, physically implements AC-First.

## Why the call graph can't answer it (and what does)

A relay toggle on an STM32F103 is a **memory store to a GPIO register**
(`GPIOx->BSRR`/`BRR`/`ODR` at `0x40010800 + port*0x400`), **not a call edge**. So
`reference/callgraph.txt` is blind to it by construction — "no relay call in the
graph" would prove nothing. The two things that *can* answer it are:

1. **Static data-flow enumeration** — follow the AC-First signal to every
   consumer and see whether any consumer materialises a GPIO address. docs/08
   already did this (below).
2. **Dynamic capture** — run the firmware and watch GPIO register writes while
   the window toggles. That is the new probe `tools/emu_gpio_acfirst.py`.

## What the existing evidence already says

docs/08 traced the AC-First signal from both ends, and **both enumerations
terminate away from any GPIO**:

**(a) Every reader of the window registers `settings+0x64…0x6e` (regs 152-157)** —
enumerated in both `[base+disp]` and direct-address forms — is a *closed set*:
the Modbus dispatch `fn_ceaa`, the per-field accessors `sub_08008d64…e40`, the
validator `sub_080132a0`, the bulk handler `sub_080341b2`, the RTC evaluator
`sub_0801eb4c`, and the change-detectors/mirror writers. **None drives a GPIO**,
and none re-derives the window condition to switch an output.

**(b) The entire downstream fate of the derived status bit**:

| location | produced by | consumed by |
|---|---|---|
| `0x2000aa5e` per-window mask | `sub_0801eb4c` | only `sub_0801eb4c` (aggregation) |
| `0x2000a758` bit24 "any window active" | `sub_0801eb4c` tail | only `sub_0801ece8` |
| `0x2000a8e6` bit4 (mirror) | `sub_0801ece8` | app/dongle **telemetry** packer `sub_080258ca` → sent by `sub_08024dfc` |

So the signal goes **window → `aa5e` → `a758` bit24 → `a8e6` bit4 → telemetry
status, and stops.** It is *reported* ("AC-First active now" to the app), not
used to actuate anything. Separately, docs/08 proved the **pushed output-priority
byte is static config** (`settings+0x17` = reg 145) and is **not** window-gated.

## Architectural reading — where the relay actually lives

"AC First" is output-priority **power routing** (prefer the grid to supply load
and charge the battery). The physical switching for that — the grid/AC
contactor, the inverter/rectifier bridges, the EPS transfer — is **real-time,
safety-critical power electronics**, which [`docs/07`](07-dsp-ac-first-mode.md)
and [`docs/09`](09-dsp-persistence-and-clock.md) place squarely in the **TI C2000
DSP** (with the redundant safety CPU). The ARM "com" MCU is comms/HMI/supervisor.

Crucially, the DSP already has **everything it needs to do time-of-day routing
itself**, without the ARM toggling anything:

- the **static output-priority mode** (reg 145 → block 0 → DSP `0xADA8`, `2` = AC
  First) — [`docs/07`](07-dsp-ac-first-mode.md);
- the **grid/AC-charge schedule windows** (regs 64-89), ingested as register
  values and evaluated **DSP-side** — [`docs/08`](08-arm-dsp-config-protocol.md);
- the **wall clock**, which the ARM **streams to the DSP every cycle**
  (`0x20009754` frame, `sub_08021df8`, six RTC bytes) — docs/08 / docs/09.

The grid-relay self-test even has its own fault code, **`E016 Relay check`**
(`FAULT_RELAY_CHECK`, [`include/inv/faults.h`](../include/inv/faults.h)) — the
ARM *displays* that fault, consistent with the DSP owning the relay and reporting
its state up, not the ARM driving it.

### The ARM does drive *some* relays — just not from AC-First

The ARM genuinely owns low-side GPIO loads: the LCD and keypad, the RS-485
driver-enable (`mb_port_set_tx`, [`docs/04`](04-modbus.md)), the buzzer, status
LEDs, fan PWM, and a user **dry-contact relay** (`MENU_DRY_CONTROL`,
[`include/inv/hmi_menu.h`](../include/inv/hmi_menu.h)). These are driven by their
**own** settings and logic, not by the AC-First window bit — the `a8e6` bit4
reader set above contains only the telemetry packer, not a dry-contact handler.

## Conclusion

On the recovered evidence, **the theory is not supported — it is contradicted.**
The ARM's AC-First window evaluation is a **status indicator that ends in
telemetry**; it does not actuate a relay, and the pushed mode it would gate is
static. The actual AC-First power routing (and any physical relay/contactor
switching) is **DSP-side**, driven by the static mode + schedule registers + the
ARM-streamed clock the DSP already receives. The ARM's own GPIO relays
(dry contact, etc.) are a separate, independently-configured feature.

**Confidence:** high on "the ARM does not toggle a relay *from the AC-First
window decision*" (two independent static enumerations in docs/08 both terminate
in telemetry; architecture agrees). Lower on the absolute negative "the ARM
drives no relay relevant to grid routing at all" — that is a DSP/safety-domain
and on-hardware question, outside this repo's scope.

## Settle it dynamically — `tools/emu_gpio_acfirst.py`

The committed probe makes the refutation reproducible the moment the ARM image
is available (`reference/com_flat.bin`; gitignored, not in the tree). It extends
the Unicorn harness to **capture every GPIO level-drive write** (`ODR`/`BSRR`/
`BRR`, all ports A-G) while:

- **Stage A** runs the evaluator caller `sub_0801ece8`, and
- **Stage B** runs the mode/status **supervisor** `sub_0801f184` — which fans out
  to the whole status-computation cluster (`sub_0801e608`/`ece8`/`ed28`/`eeb0`/
  `effa`/`f11c`), the far likelier home of a mode-driven relay update than the
  narrow evaluator,

at an **in-window** RTC (03:00) vs an **out-of-window** RTC (05:00), and diffs the
GPIO writes. Pins that toggle identically in both runs are housekeeping (LCD,
RS-485 DE, keypad, fan/LED); a **window-dependent** level write would be the
AC-First relay.

**Expected result** (prediction from the static analysis): no window-dependent
GPIO write on either stage — corroborating docs/08's "signal ends in telemetry".

```bash
# with the reconstructed ARM image present:
python3 tools/hex2bin.py <com>.hex reference/com_flat.bin --base 0x08000000
python3 tools/emu_gpio_acfirst.py
```

> Caveat (shared with `tools/emu_acfirst.py`): `sub_0801f184` is a gated
> scheduler task; a cold single-pass run does not exercise every branch. A null
> result proves no relay is toggled along the paths a cold run reaches — it
> corroborates the static enumeration, it does not replace an on-hardware check.
