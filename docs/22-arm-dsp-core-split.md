# Where the state machine lives — the ARM/DSP split, traced through IR_STATE

> **Authoritative wiring:** the USART2↔safety-CPU link is specified in [`docs/wiring/ARM-USART2-safety.md`](wiring/ARM-USART2-safety.md). **Note:** the table cell calling PV voltage "DSP telemetry, verbatim" is stale — the measured values are the safety CPU's own (see the correction note below it, and docs/29).

A long-standing open question was whether the core operating-state machine lives
on the ARM "com" MCU or the TI C2000 DSP, and the evidence looked contradictory:
the **AC-First time windows are evaluated against the RTC on the ARM** (the DSP
has no clock, [`docs/09`](09-dsp-persistence-and-clock.md)/[`docs/14`](14-arm-gpio-relay-acfirst.md)),
yet the **operating mode reads like a DSP quantity**. This note resolves it by
tracing the single most load-bearing value — **Modbus input register 0
("State / operating mode")** — from the wire back to its origin.

## The provenance of IR_STATE (reg 0), proven

```
Modbus read of input reg 0
   └─ served by  sub_0803289c(reg)        the input-register getter
        reg 0 case (0x08032de6):  return *(u8*)(0x2000a0d8 + 0x90)   ← IR_STATE lives here
   (getter identity is certain: reg 1/2 → PV volts 0x20009e54+0x4c/0x4e,
    reg 3 → hardcoded 0 = "no 3rd MPPT" on the 2-tracker build, reg 4/5 → battery bank)

0x2000a0d8 + 0x90  (= 0x2000a168)
   └─ written by EXACTLY ONE function:  sub_0801b480   the ARM state *classifier*
        reads a mode byte + flags, writes one of {0x02,0x11,0x14,0x19,0x80,0x88,0xC0,…}

sub_0801b480 inputs:
   • 0x20009e54[0] / [1]   the received operating-mode byte(s)     (primary)
   • 0x20009048[5..8]      error/fault flags (shared telemetry/register array)
   • 0x2000a5d0, 0x2000a6c4  status/qualifier bytes

0x20009e54[0]
   └─ written by  sub_08024d74 :  *(u8*)(0x20009e54+0) = RXframe[0x20008084 + 4]
        (gated on a received frame length ≥ 0x54; also copies +0xd0/+0xd4 status
         dwords and a second mode byte from +0x0d)

0x20008084  = an RX staging buffer for **USART2** (0x40004400), filled by the
             0x0801c7xx/c8xx/c9xx link cluster.
```

So reg 0 is **not** a single DSP byte copied verbatim, and it is **not** an
independent ARM decision. It is an **ARM classification of a received telemetry
byte**:

- `sub_0801b480` mostly **passes through** the received mode byte `0x20009e54[0]`
  (the common branch literally stores `state = received_byte`), with two overlays:
  a **fault / not-running override** (→ `0x02`) when the error flags in
  `0x20009048[5..8]` or the received status bytes are set, and a
  **canonicalisation** step (when the `[1]==8` qualifier is present it validates
  the composite against the known `states.h` values, defaulting to `0x08`).

## The upstream peer — decoded, and it is a control-processor (DSP) link

The mode byte arrives on **USART2**. Decoding the frame it comes in confirms the
peer is a **control processor carrying DSP-domain telemetry**, not an external
meter/dongle:

**It is the EG4 frame family** (docs/05's anchor). The driver `sub_080259d8`
validates `0x20008084` as `addr · type `**`[1]==1`**` · … · CRC-16`, where the CRC
is the table-driven EG4 Modbus CRC-16 (`sub_08014bec`, init `0xFFFF`, lo/hi tables
`0x0803eb70`/`0x0803ec70` — the lookup-table twin of the DSP's own `0xA001` CRC).
The `type==1` byte is the same telemetry/config type as the DSP config frames
(docs/08) and the DSP's own uplink (`[1]=1`, docs/10).

**It carries the inverter's own real-time power measurements.** The input-register
getter `sub_0803289c` sources these straight from the USART2 bank `0x20009e54`:

| IR reg | quantity | bank offset |
|---|---|---|
| 1 / 2 | **PV1 / PV2 voltage** | `+0x4c` / `+0x4e` |
| 12 / 13 / 14 | **grid voltage R / S / T** | `+0x20` / `+0x28` / `+0xb6` |
| 15 | **grid frequency** | `+0x5e` |
| 0 (via the classifier) | **operating mode** | `+0x00` |

PV voltage, three-phase grid voltage and grid frequency are produced only by the
power-electronics controller (grid-sync + MPPT) — i.e. the **DSP**. (Battery V/SOC
come from a *different* bank, the CAN/BMS one; energy counters are ARM-accumulated
in `0x20009954`.) So USART2 is an **inter-processor link bearing DSP telemetry**,
confirming the mode's origin.

> Residual limit (as first written — **now resolved in the two notes below**:
> relayed via the redundant safety CPU, docs/23/30): firmware alone couldn't yet
> prove USART2 was *physically* the DSP's second SCI versus routed via the third
> (redundant safety) CPU. But the **data is DSP-domain** (operating mode + the DSP's
> own V/F/PV measurements, EG4-framed), which is what matters for the split below.
> **USART3** is the confirmed DSP SCI-B (bootloader + CRC, docs/05); USART2 is the
> complementary telemetry direction. A DSP-side cross-check to pin the physical
> port (SCI-A vs relayed) is specced in [`docs/23`](23-dsp-sci-a-crosscheck-handoff.md).

> **DSP-side cross-check result (docs/23): relayed, not a direct DSP SCI-A.** The DSP
> *does* produce this exact frame — its builder `FUN_00096EE8` emits `type=1`,
> big-endian, `0xA001`-CRC with the **operating-mode byte at `+4`** (from the DSP
> state machine) + PV/grid/freq — but it transmits it on **SCI-B**, the same port as
> the config push (`FUN_0009DD14→FUN_0009D358→`SCI-B = **USART3**). The DSP has no
> second ARM-facing telemetry port (SCI-A carries unrelated bulk records at ~9600;
> only SCI-B runs ~19200). So the mode's **origin on the DSP is confirmed**, but
> **USART2 is not the DSP's second SCI** — the DSP-domain data on USART2 is relayed.
>
> **RESOLVED (docs/30): the USART2 peer is the redundant / "safety" CPU.** The ARM
> *reports* the safety cross-check status straight out of the USART2 frame — the
> Modbus fault word (`STATUS+0x88`) is copied from `BANK+0xd0`, a BE u32 at USART2
> frame `+5` (`sub_08024d74`/`sub_0801b480`), so **bit 27 = E027
> (`FAULT_CPU_SAMPLE_MISMATCH`)** is the frame's own bit; the grid warnings and the
> peer version byte (`BANK+2`, HR 10 low) also arrive on USART2; and the
> peer-comms-loss bit `0x20000` (E017) is driven by the USART2 driver's own link-health
> tracker. So USART2 carries the safety CPU's **own grid/PV measurements** + the
> DSP-originated operating-mode byte (`BANK+0`), **plus** its agreement/version status
> (see the "bank is the safety CPU's own, not DSP-relayed" section below). (Full bank
> field map: [`docs/33`](33-usart2-telemetry-bank.md).)
> Full chain:
> `DSP —SCI-C 9600— safety CPU —USART2 19200 RS-485— ARM` (docs/29/30). The ARM *also*
> receives the DSP's own `0x49` telemetry directly on **USART3** (SCI-B, docs/10), but
> the classifier builds IR_STATE + the fault word from the **USART2/safety-CPU** bank.

## The split, and why the evidence looked contradictory

| Responsibility | Lives on | Mechanism |
|---|---|---|
| **Real-time power FSM** — decide on-grid / off-grid / charging / fault from live electrical conditions | **DSP** | runs the power stage; emits the operating-mode byte + measurements as telemetry |
| **State classification → `IR_STATE`, faults, measurements** | **ARM** | `sub_0801b480` classifies received telemetry; getters (`sub_0803289c`) serve it as Modbus input regs + the HMI |
| **Supervisory *commanding*** — RTC-based AC-First windows, output priority, charge/discharge schedule, config | **ARM** | evaluated ARM-side (e.g. `sub_0801eb4c` vs the RTC) and **pushed to the DSP** over the config link (docs/08), which changes what the DSP then does |

It is a **feedback loop**, which is exactly why the evidence seemed to conflict:

```
   ARM commands  ──(config push, incl. RTC-derived AC-First schedule)──▶  DSP
   DSP executes the power stage, decides the real operating mode
   ARM classifies the DSP's telemetry  ──▶  IR_STATE (reg 0), faults, HMI
```

- **AC-First timing on the ARM** is real — it is a *command input* to the DSP
  (the DSP has no clock, so the ARM must schedule). ✔
- **IR_STATE reflecting the DSP** is real — it is a *classification of the result*
  the DSP reports. ✔

Neither contradicts the other; they are opposite ends of the same loop. The
**core power state machine is on the DSP**; the ARM is the **supervisor** that
both *drives* it (schedules/commands) and *reports* it (classifies telemetry into
the Modbus/HMI model and gates its relays).

## Data-flow example — the PV registers (and the MPPT chip)

The same classify-vs-command split shows up in the PV telemetry, and it answers
"does the ARM read the MPPT controller directly?" — **no, it goes through the DSP.**

The input-register getter `sub_0803289c` sources the PV registers thus:

| IR reg | quantity | source |
|---|---|---|
| 1 / 2 | PV1 / PV2 **voltage** | **DSP telemetry, verbatim** — `0x20009e54+0x4c/0x4e` (the USART2 bank) |
| 3 | PV3 voltage | hardcoded `0` (no 3rd MPPT on the 2-tracker build) |
| 7 / 8 | PV1 / PV2 **power** | `0x2000a0d8+0x28/0x2c` — **computed on the ARM** |
| 9 | PV3 power | hardcoded `0` |

- **Voltage** is served verbatim from the USART2 bank.
  > **Correction (DSP-side, [`docs/29`](29-safety-cpu.md)):** USART2's peer is the
  > **safety CPU** (docs/30), and the DSP forwards it **no** grid/PV — over SCI-C the
  > DSP sends the safety CPU only its operating-state byte. So this PV voltage is the
  > **safety CPU's own measurement**, not a DSP value relayed. Only `BANK+0` (the
  > mode byte) is DSP-originated; the measured V/F/PV in this bank are the safety
  > CPU's independent samples.
- **Power** is *not* a copied field: `sub_0801a678` does the float `V·I` (with the
  `0.5f` averaging term) into accumulators `0x2000a818`/`0x2000a81c`, and
  `sub_0801b034` converts and stores them to `STATUS+0x28/0x2c` (alongside
  Pcharge/Pdischarge/Pinv). Its inputs are the DSP-supplied V/I.

The **`mppt` controller** (a 4th processor, [`docs/13`](13-mppt-controller.md))
publishes PV V/I/P on its own EG4-Modbus UART — but the **DSP** is the master that
polls it; the ARM never reads the MPPT directly. The path is **MPPT → DSP →
(USART2) → ARM**, and the ARM derives the power terms. (Consistent with docs/16:
the com MCU configures *no* analog inputs — it does no sensing of its own.)

So, again: the ARM is the **classifier/aggregator/reporter** over DSP telemetry
(serve voltage, compute power, classify state), while the raw measurements and the
real-time control live on the **DSP** and the sensor-facing **MPPT** chip.

## Implications for the reimplementation

Our ARM firmware's "mode" module should therefore be **two things, not a power FSM**:

1. **A classifier** `received_mode_byte + fault_flags → IR_STATE bitmask`, a pure
   host-testable function mirroring `sub_0801b480` (pass-through + fault override
   + canonicalisation against `states.h`). Its input is DSP telemetry (once the
   DSP-link **RX** parser exists; today our link is TX-only).
2. **The supervisory/commanding pieces** — AC-First schedule, output priority,
   transfer-relay sequencing — which feed the DSP and the relays.

The real-time power FSM is **not** ours to write; it stays on the DSP and we
honour its telemetry/command contract.

## Method note (so this is reproducible)

- Getter: `sub_0803289c` is reached from the frame serializer's func-4 low-register
  path (`sub_0803373c` → `bl sub_0803289c`); its reg-0 case is at `0x08032de6`.
- Writers/readers were enumerated with `tools/ramxref.py`; address materialisation
  was checked for both pc-relative `ldr` and `movw`/`movt` pairs (that is how
  `0x2000d0e4` and `0x2000ce5c` were shown to be phantom — formed nowhere).

## 07-series re-pin: the classifier addresses above are 05-series (docs/39 T06)

The function/RAM addresses in this note were recovered from a **05-series**
image. Against the canonical **07-series** oracle (`ceaa-07xx_vE_260214`), they do
**not** hold, which blocks the T06 factory oracle. Verified while implementing
T06 (classifier entry + its telemetry/STATUS base):

- **`sub_0801b480` is not the classifier here.** At that address the 07 image has
  a periodic housekeeping task (counter `0x2000dac6`, RTC tick `sub_08018bc0`),
  not a mode classifier. **The real 07 classifier/state-machine is `sub_0801a678`**
  (RESOLVED, T02b): it reads the telemetry bank's fault (`0x2000ce5c+0xd0`) and
  warn (`+0xd4`), composes `STATE+0x98` (fault word) / `STATE+0x9c` (warn word),
  and writes **IR_STATE at `0x2000d0e4+0xa0`** from the received mode byte
  (`bank+0`). Verified by feeding a USART2 mode byte on the wire (T02a) and
  watching `0x2000d0e4+0xa0` track it.
- **The telemetry bank base `0x20009e54` is stale for 07 — the real base is
  `0x2000ce5c`** (RESOLVED, T02a, docs/33). `0x20009e54` is referenced nowhere in
  the 07 image; the nearby `0x20009e50` is a USART2 RX scratch buffer that the
  plumbing fills with `'i'`/`'-'` (`0x2d`) placeholder bytes — which is why a dump
  of `0x20009e54` reads as `2d 2d 2d …`. The **actual** USART2 telemetry bank has
  **22 literal refs at `0x2000ce5c`**, is what the distributor `sub_0802677a` +
  tag parser `sub_08025ab8` write and the getter `sub_0803289c` reads, and seeding
  it (or feeding a wire frame into it) makes `test_safety_cpu_telemetry_reaches_modbus`
  **and** `test_usart2_frame_reaches_modbus` pass. `FAC_SAFETY_BANK` is corrected
  to `0x2000ce5c`. (Other docs that still cite `0x20009e54` as the 07 bank —
  16/18/23/29/30/32/37, wiring — read `0x2000ce5c`; same field offsets.)
- **`0x2000a0d8`+`0x90` (the 05 IR_STATE) is referenced nowhere in 07** — the 07
  IR_STATE is **`0x2000d0e4+0xa0`** (confirmed: the PC6 relay decider `sub_08016ec6`
  reads exactly that byte to gate the run-enable relay; docs/18).
- **The getter is reached, but its reads during a Modbus `IR 0` poll land in
  Modbus/response frame buffers** (`0x2000a304` is an ~800-byte RX/command buffer
  indexed at `+0x44e`, parsed by `sub_0801b6be` matching command bytes
  0x21/0x31/…), not a STATUS struct — so dynamic read-hooking does not isolate
  IR_STATE either.
- **Dynamically, the classifier only reclassifies on a received USART2 frame**
  (the RX ingest) — which the harness **now runs** (T02a cracked it): feeding a
  frame drives `sub_0801a678` and `0x2000d0e4+0xa0` (IR_STATE) tracks the fed mode.

**The 07 classifier entry (`sub_0801a678`) and IR_STATE (`0x2000d0e4+0xa0`) are now
pinned** (see the resolved bullets above). The relay deciders are likewise pinned
(docs/18: PB2/PC6 = `sub_08016ec6` reads IR_STATE `+0xa0`). A clean PC6 state→relay
demo is not reachable from USART2 alone — the relay blinks (state-independently)
while ARM-local warnings (`STATE+0x9c`, W006/W008) are present, and those gate on a
whole-inverter status struct `0x2000d890` the USART2 peer can't clear (docs/39 T02b). Re-pinning that map is a
prerequisite shared by T06b (the classifier oracle), the relay tests, and the
safety-telemetry test, and is adjacent to T02 (running the USART2-ingest/
classifier task in the sim). Until then, our `inv_classify()`
(`src/state/classify.c`) is grounded in the **documented** behaviour (this doc +
the IR000 / IR060_063 register docs) and host-tested (`tests/test_classify.c`),
with the two unverified points flagged in-code: the fault/not-running **state
override target** and the **non-canonical-byte default**.

### What a re-pinner needs to find (for T06b)
1. The 07 **telemetry bank base** (where the getter sources IR 1/2/12-14 etc.) —
   start from `sub_0803373c`'s func-4 path and follow the getter's reg→RAM reads
   for a *measurement* register (not reg 0, which hits the frame buffer).
2. The 07 **IR_STATE byte** (getter reg-0 source).
3. The **classifier** = the one function that writes that byte from a received
   mode byte; expect it near the 05 site (the `0x0801b4xx–0x0801b9xx` cluster).
4. Then add a `ClassifyBackend` to a `tests/classify_contract.py` (seed the mode
   byte + fault flags, call the classifier in isolation, read IR_STATE/60-63) and
   an `OursBackend` (call `inv_classify` by symbol, like `timewindow_contract.py`),
   and sweep mode bytes 0x00–0xFF × fault conditions as the shared vectors.
