# Where the state machine lives — the ARM/DSP split, traced through IR_STATE

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

## The honest caveat about the upstream peer

The mode byte arrives on **USART2**, and firmware alone does **not** pin USART2's
physical peer — [`docs/05`](05-dsp-link.md)/[`docs/16`](16-arm-io-map.md) list the
five same-framed links (DSP SCI-B, BMS, meter/CT, MPPT, external RS-485 dongle)
and note the UART↔peer map needs the schematic. What *is* confirmed: **USART3** is
the DSP's SCI-B (the bootloader `0x21/0x22/0x23` and the shared CRC-16 prove it,
docs/05). The operating mode is this unit's own real-time power state, which only
the **DSP** produces — so the telemetry carrying it is almost certainly a DSP
link (plausibly a second DSP SCI on USART2, complementary to the SCI-B config
link on USART3). That origin is a **strong inference, not a proof**; the chain
above is proven only back to "received on USART2."

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
