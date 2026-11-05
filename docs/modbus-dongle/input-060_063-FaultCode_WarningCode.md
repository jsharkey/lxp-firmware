# IR 60-63 — FaultCode / WarningCode (32-bit bitfields)

> **Dongle Modbus**, input registers (func `0x04`, read-only). Authoritative. See
> the [index](README.md).

| reg | name | note |
|---|---|---|
| IR 60 | FaultCode L | fault bitfield, low word |
| IR 61 | FaultCode H | fault bitfield, high word |
| IR 62 | WarningCode L | warning bitfield, low word |
| IR 63 | WarningCode H | warning bitfield, high word |

Each is a **32-bit bitfield** (bit *n* = fault/warning *n*). 32-bit values use the
dongle's word+byte-swapped encoding (see [index](README.md)).

## Where the data comes from

**The USART2 bank — the safety CPU's cross-check result**, relayed over USART2.
This is the ARM-side proof that the USART2 peer is the safety CPU
([`docs/30`](../30-safety-cpu-arm-handoff.md), [`docs/33`](../33-usart2-telemetry-bank.md)):

| served as | internal word | from bank | frame off |
|---|---|---|---|
| IR 60/61 FaultCode | `STATUS+0x88` | `BANK+0xd0` | frame `+5` |
| IR 62/63 WarningCode | `STATUS+0x8c` | `BANK+0xd4` | frame `+9` |

The classifier `sub_0801b480` merges each relayed word with an ARM-local
accumulator before serving it. Most bits pass through verbatim; a few are set
locally:

- **Faults:** bits 0 (E000) and 17 (E017) are set by the ARM; **E027 (bit 27) is
  the frame's own bit** — it is the safety CPU's "sample mismatch" verdict.
- **Warnings:** grid warnings **W016/17/18** (bits 16-18, and the other high bits)
  come from the frame; low bits 0-9 incl. **W008** (FW-version mismatch) are
  **ARM-computed** (W008 from the version compare, [`holding-009_010-FW-versions`](holding-009_010-FW-versions.md)).

> **Fault/warn order (corrected per [`docs/33`](../33-usart2-telemetry-bank.md)).**
> Earlier drafts (docs/30) swapped which bank word was fault vs warn; the table
> above is the corrected mapping (fault = `BANK+0xd0`, warn = `BANK+0xd4`).

## Fault codes (E000-E031) — spec Table 10

| bit | fault | bit | fault |
|---|---|---|---|
| 0 | E000 Internal communication fault 1 | 16 | E016 Relay check fault |
| 1 | E001 Model fault | 17 | E017 Internal communication fault 2 |
| 2 | E002 rsvd | 18 | E018 Internal communication fault 3 |
| 3 | E003 rsvd | 19 | E019 BUS voltage high |
| 4 | E004 rsvd | 20 | E020 EPS connection fault |
| 5 | E005 rsvd | 21 | E021 PV voltage high |
| 6 | E006 rsvd | 22 | E022 Over-current protection |
| 7 | E007 rsvd | 23 | E023 Neutral fault |
| 8 | E008 Paralleling CAN comm lost | 24 | E024 PV short |
| 9 | E009 Master unit lost in parallel | 25 | E025 Radiator temperature out of range |
| 10 | E010 Multiple master units in parallel | 26 | E026 Internal fault |
| 11 | E011 AC input inconsistent in parallel | **27** | **E027 Sample inconsistent between Main CPU and redundant CPU** |
| 12 | E012 UPS short | 28 | E028 rsvd |
| 13 | E013 Reverse current on UPS output | 29 | E029 rsvd |
| 14 | E014 BUS short | 30 | E030 rsvd |
| 15 | E015 Grid phases inconsistent (3ph parallel) | 31 | E031 Internal communication fault 4 |

> **E027** confirms the safety-CPU architecture from the spec side: the inverter's
> own documented fault is a "Main CPU vs redundant CPU sample mismatch". See
> [`docs/wiring/DSP-SCI-C`](../wiring/DSP-SCI-C.md) and [`docs/29`](../29-safety-cpu.md).

## Warning codes (W000-W031) — spec Table 10

| bit | warning | bit | warning |
|---|---|---|---|
| 0 | W000 Battery communication failure | 16 | W016 Grid power outage |
| 1 | W001 AFCI communication failure | 17 | W017 Grid voltage out of range |
| 2 | W002 AFCI high | 18 | W018 Grid frequency out of range |
| 3 | W003 Meter communication failure | 19 | W019 rsvd |
| 4 | W004 Charge & discharge forbidden by battery | 20 | W020 PV insulation low |
| 5 | W005 Auto test failed | 21 | W021 Leakage current high |
| 6 | W006 rsvd | 22 | W022 DCI high |
| 7 | W007 LCD communication failure | 23 | W023 PV short |
| **8** | **W008 FW version mismatching** | 24 | W024 rsvd |
| 9 | W009 Fan stuck | 25 | W025 Battery voltage high |
| 10 | W010 rsvd | 26 | W026 Battery voltage low |
| 11 | W011 Parallel number out of range | 27 | W027 Battery open circuit |
| 12 | W012 rsvd | 28 | W028 EPS overload |
| 13 | W013 rsvd | 29 | W029 EPS voltage high |
| 14 | W014 rsvd | 30 | W030 Meter reverse connection |
| 15 | W015 Battery reverse connection | 31 | W031 DCV high |

> **W008** (bit 8) is the version-mismatch warning the ARM computes locally from
> the per-processor FW-version bytes — see
> [`holding-009_010-FW-versions`](holding-009_010-FW-versions.md).

The internal DTC (IR 6) and the BMS fault/warn words (IR 99/100) are separate —
see [`input-006-InternalFault`](input-006-InternalFault.md) and
[`input-081_106-BMS`](input-081_106-BMS.md). The firmware's own enum lives in
[`include/inv/faults.h`](../../include/inv/faults.h).
