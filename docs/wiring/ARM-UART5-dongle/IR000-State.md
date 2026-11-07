# IR 0 — State (operating mode)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See
> the [index](registers.md). This is the register the datalogger reads to show the
> inverter's operating mode.

| reg | name | unit | range |
|---|---|---|---|
| IR 0 | State | — (bitmask) | see table |

## Where the data comes from

**The USART2 bank, and it is the one DSP-originated field in that bank.** The DSP
computes the real-time working-state byte; it hands it to the **safety CPU** over
SCI-C, which relays it to the ARM in the USART2 telemetry frame at **`BANK+0`**
(frame offset `+4`). The ARM's classifier `sub_0801a678` writes it to `IR_STATE`
**verbatim** — a pure pass-through, no canonicalisation and no fault override
(pinned on the 07 oracle, docs/39 T06b) — served to the dongle by the getter
`sub_0803289c`. The DSP itself encodes Fault (`0x01`) / Standby (`0x00`) into the
mode byte, so the ARM does not re-derive the state; a relayed fault appears in the
FaultCode ([`IR060_063`](IR060_063-FaultCode_WarningCode.md)), not here.

- Bank/relay path: [`docs/33`](../../33-usart2-telemetry-bank.md),
  [`docs/wiring/ARM-USART2`](../../wiring/ARM-USART2-safety.md),
  [`docs/wiring/DSP-SCI-C`](../../wiring/DSP-SCI-C-safety.md).
- ARM/DSP responsibility split: [`docs/22`](../../22-arm-dsp-core-split.md)
  (07 image: `IR_STATE` = byte at `0x2000d0e4+0xa0`, classifier `sub_0801a678`,
  getter `sub_0803289c`; the `0x2000a0d8+0x90` / `sub_0801b480` in older notes are
  05-series).

The same `IR_STATE` value also **gates the power-path relays** inside the ARM
(run-enable follows the mode) — see [`docs/18`](../../18-power-path-relays.md). That
is an internal consumer, not something the dongle sees.

It also **drives the front-panel LED ring's colour**: the mapper at `0x08016fcc`
reads this operating-mode byte (`0x2000d0e4+0xa0`) plus the two companion
extended-status dwords (`+0x98`/`+0x9c`) and selects the ring's mode/colour — a
running state shows the green pattern, a warning the yellow/amber one. Full chain
(PD15 / TIM4-CH4 PWM+DMA serial LED) in [`docs/40`](../../40-led-ring.md).

## Operating modes (spec Table 9)

| code | mode | code | mode |
|---|---|---|---|
| `0x00` | Standby | `0x20` | AC Charge |
| `0x01` | Fault | `0x28` | PV + AC charge |
| `0x02` | Programming (FW update) | `0x40` | Battery off-grid |
| `0x04` | PV on-grid | `0x80` | PV off-grid *(unstable, not advised)* |
| `0x08` | PV Charge | `0x88` | PV charge + off-grid |
| `0x0C` | PV Charge + on-grid | `0xC0` | PV + battery off-grid |
| `0x10` | Battery on-grid | | |
| `0x14` | PV + Battery on-grid | | |

## Nuance

`State == 2` is **Programming** (firmware update), not "AC First". An earlier
relay-gating draft misread `== 2` as AC-First output-priority; corrected in
[`docs/18`](../../18-power-path-relays.md)/[`docs/16`](../../16-arm-io-map.md).
Output-priority is a *holding* register —
[`HR145-OutputPrioConfig`](HR145-OutputPrioConfig.md).

## On the LCD (EG4 12000XP manual)

DATA MENU **Other tab**: `Status` = current status, `NextStatus` = next status. The manual's status-code table (§17.3) is the same code set as IR 0 but adds two the Modbus operating-mode table omits: `0x11` **Bypass** and `0x19` **PV Charge + Bypass**.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **State classifier:** [`test_classify.c`](../../../tests/test_classify.c) (`make test`) covers `inv_classify()` — IR 0 is a **pure pass-through** of the mode byte (canonical, LCD 0x11/0x19, and non-canonical bytes alike), and a relayed/local fault composes into the FaultCode without changing IR 0 (docs/22, T06a/T06b). `main.c` publishes IR 0 via `state_publish()`.
- **Factory oracle + ours e2e (T06b):** [`test_arm_sim_factory_only.py`](../../../tests/test_arm_sim_factory_only.py) `test_usart2_classifier_is_pure_passthrough` + `test_usart2_mode_reaches_ir_state` (mode byte on the USART2 wire → IR_STATE verbatim; fault → FaultCode, not IR 0); ours [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) `test_usart2_mode_classified_passthrough_e2e`.
- **IR 0 (State):** engine read path — [`test_modbus.c`](../../../tests/test_modbus.c) reads `IR_STATE`. Also the run-enable relay contract: [`arm_sim_contract.py`](../../../tests/arm_sim_contract.py) `RUN_STATES`/`NONRUN_STATES` drive PC6 from the State value, held by `test_relay_follows_working_mode` in [`test_arm_sim_self_only.py`](../../../tests/test_arm_sim_self_only.py) / [`test_arm_sim_factory_only.py`](../../../tests/test_arm_sim_factory_only.py).
