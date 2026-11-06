# Modbus-RTU slave

> **Dongle registers:** per-register facts for the dongle Modbus surface (what each register means, where its data comes from, side-effects of writes) now live in [`docs/wiring/ARM-UART5-dongle/`](wiring/ARM-UART5-dongle/registers.md) (authoritative). This doc keeps the slave engine, framing and 40-register query-rule contract.

> **Authoritative wiring:** the external Modbus port (pins, peer, framing) is now specified in [`docs/wiring/ARM-UART5-dongle/README.md`](wiring/ARM-UART5-dongle/README.md). This doc keeps the register/framing contract and the engine design.

The com MCU is a Modbus-RTU **slave** on RS-485. This is the first real
subsystem of the reimplementation and the most fully specified one (the public
EG4 18kPV-12LV protocol doc is the authority; the 12000XP shares it).

- Engine (transport-agnostic, host-testable): `src/modbus/modbus.c`
- UART/RS-485 port: `src/modbus/modbus_port.c` (currently bound to USART3 in our
  skeleton; the factory dongle port is **UART5** — see the Status note below and
  [`docs/26`](26-dongle-firmware.md))
- Register map: `include/inv/modbus_map.h`
- API: `include/inv/modbus.h`
- Tests (host): `tests/test_modbus.c` → `make test`

## Link

RS-485, UART, **19200 bps, 8N1** (per the EG4 spec; our skeleton uses 19200 on
USART3). Min polling period 1 s. Register width 2 bytes.
Function codes: `0x03` read holding, `0x04` read input, `0x06` write single,
`0x10` write multiple (spec: only serial number + time).

> **Observed baud on the factory dongle port differs from the spec.** The ARM
> configures its external dongle UART (**UART5**) at **9600**, not 19200 (dynamic
> `USART_BRR` read — [`docs/25`](25-modbus-register-spaces.md)/[`docs/13`](13-mppt-controller.md));
> 19200 is the rate on **USART3** (the DSP link). The dongle's own baud is
> field‑configurable ([`docs/26`](26-dongle-firmware.md)), so it is set to match
> UART5. Treat 9600 as the value to use on the real dongle port pending a bus
> capture; the register map and framing below are baud‑independent.

## Framing (EG4/Luxpower variant — not stock Modbus)

Two differences from textbook Modbus: a **10-byte `SN` serial number** follows
the function code in every frame, and multi-byte fields are **little-endian**
on the wire (`0x01 0x02` → `0x0201`). CRC is Modbus CRC-16 (poly `0xA001`,
init `0xFFFF`), appended low byte then high byte.

```
read req  (03/04): addr func SN[10] startLo startHi numLo numHi            CRClo CRChi
read resp        : addr func SN[10] startLo startHi nBytes [vLo vHi]*N      CRClo CRChi
write1 req (06)  : addr func SN[10] regLo regHi valLo valHi                 CRClo CRChi   (echoed)
writeN req (10)  : addr func SN[10] startLo startHi numLo numHi nB [v..]    CRClo CRChi
writeN resp      : addr func SN[10] startLo startHi numLo numHi             CRClo CRChi
error            : addr func|0x80  SN[10] startLo startHi excCode           CRClo CRChi
```

32-bit quantities (energy counters, runtime, …) are two consecutive 16-bit
registers (`_L` then `_H`); the engine serves them as plain 16-bit regs and the
application composes the 32-bit value. The doc's 32-bit "word + byte reversed"
rule is a *decoding convention for the master*; on our wire each register is
just little-endian, which the L/H split already satisfies.

## Related: register spaces and the several uses of "Modbus"

The function code selects the **register space**, and holding (`0x03/0x06/0x10`,
read-write settings) and input (`0x04`, read-only telemetry/status) are
**independent number lines** — the same number means different things in each
(e.g. *holding* 126-131 = OptimalChg_DisChg config vs *input* 126 = a status
word). The same EG4 frame envelope is also reused for the external dongle, the
ARM↔DSP link, and firmware update. Both traps, plus a worked AC-First-window
example, are written up in [`docs/25`](25-modbus-register-spaces.md).

## Query grouping rule

A request may span at most **40 registers** and must **not cross a 40-register
group boundary** (groups 0–39, 40–79, 80–119, …). Violations return exception
`0x02` (illegal address). Enforced in `query_span_ok()`.

## Status & TODO

- [x] CRC-16, frame parse/validate, address + optional SN filter
- [x] 0x03/0x04/0x06/0x10 handlers, exception responses, 40-reg group rule
- [x] Host unit tests (`make test`, 19 checks)
- [x] USART3 port (19200 8N1) with inter-frame gap framing
- [x] **Which UART is the external Modbus/dongle port — resolved to UART5, not
      USART3.** The external dongle firmware ([`docs/26`](26-dongle-firmware.md))
      proves the dongle is an **RS-485 half-duplex master** (datalogger), so it
      sits on the ARM link where the ARM is the **slave** — **UART5** (PC12/PD2,
      DE≈PA15), per [`docs/16`](16-arm-io-map.md). **USART3 is the ARM→DSP control
      link**, not the dongle; it reuses the same EG4 frame family, which is why
      this engine was first ported there. The transport-agnostic engine is
      unaffected; only the *port* binding moves (USART3→UART5). The RS-485 DE/RE
      GPIO (PA15) still needs wiring into `mb_port_set_tx()`.
- [ ] Populate input registers from live telemetry (needs the DSP link)
- [ ] Holding-register range validation + persistence (EEPROM/flash layout)
- [ ] Hardware bring-up test against a real monitoring tool
