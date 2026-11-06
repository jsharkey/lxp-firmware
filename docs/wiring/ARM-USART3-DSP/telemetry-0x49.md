# Telemetry frame (`SOF 0x49`) — DSP → ARM

> **DSP→ARM**, the return direction of the type-1 block protocol on this same
> SCI-B/USART3 wire. See the [index](fields.md) and [`frame-header`](frame-header.md).

The DSP mirrors its state back to the ARM with the **same block-tagged framing** as
the config push, but **SOF `0x49` ('I')** instead of `0x41`:

```
off 0x00  SOF   : 0x49 ('I')
off 0x01  type  : 0x01
off 0x02  0x00
off 0x03  len   : 0x36 (54)
off 0x04  working-state byte (DSP DAT_0000AD64 — the DSP's operating/working state)
off 0x05 .. 0x13  status/flags header
off 0x14  block id
off 0x15  block payload: big-endian — PV / grid-V / frequency, filled by FUN_00092110
 ...      CRC-16 trailer
```

- **DSP builder:** `FUN_00096EE8` (→ `FUN_0009DD14` → `FUN_0009D358`, which writes
  the **SCI-B** TXBUF pointer `DAT_0000aefe` — i.e. out ARM **USART3**, docs/23).
  The bulk filler `FUN_00092110` dispatches on the **same 9 block ids (0–8)** the
  config parser `FUN_00092EE2` uses — one symmetric, SN-less, big-endian frame in
  both directions.
- **ARM parser:** `FUN_08025ab8(0x14)` (reads block id `0x14` + BE values `0x15+`
  into a struct); RX state machine `FUN_0801bb0e` keys on `0x49`.
- **Byte `[0x04]` is the DSP's working-state** — the mode the DSP computes; this is
  the field `docs/22`'s split analysis cares about.

> **Important (docs/22/30):** the ARM's **authoritative classified operating state,
> core input registers and fault word are NOT built from this `0x49` frame** — they
> come from the **safety CPU on USART2** (relaying DSP-domain data). This USART3
> `0x49` telemetry is a parallel DSP-direct stream; which fields the ARM actually
> consumes from it vs. from USART2 is covered in
> [`ARM-USART2`](../../wiring/ARM-USART2-safety.md) and [`docs/22`](../../22-arm-dsp-core-split.md).

Per-field payload semantics mirror the config blocks' targets (same block ids), so
the config per-block docs are the layout reference; the telemetry's own measured
quantities (PV/grid/freq) are documented from the ARM-consumer side in
[`docs/33`](../../33-usart2-telemetry-bank.md) (the equivalent values as served).
