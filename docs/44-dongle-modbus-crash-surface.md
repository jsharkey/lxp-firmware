# 44 — Dongle Modbus crash/freeze surface (can the datalogger wedge the ARM?)

**Question.** The external datalogger ("dongle") is a Modbus **master** on the
RS-485 link and the ARM is the **slave**; the dongle is a transparent byte
conduit that can put *arbitrary* bytes on the bus
([`docs/26`](26-dongle-firmware.md), [`docs/wiring/ARM-UART5`](wiring/ARM-UART5-dongle/README.md)).
So: is there any frame — corrupt wire data, an over-long length, a hostile
register count, or a particular holding-register *value* — that **crashes or
freezes** the ARM "com" MCU? We want the answer written down so our
reimplementation inherits the defences on purpose, not by accident.

**Short answer: no crash or hard freeze was found.** The register server is
defensively coded end to end — bounded frame assembly, CRC gate, a register
count cap, a `switch`-with-default register dispatch, and only constant
divisors. Static RE + dynamic injection against the `ceaa-07xx` image together
found **no** read, write-single, write-multiple, extended-function, out-of-range
register, or holding-register value that faults or permanently hangs the core.
The genuine findings are **spec deviations and availability quirks**, now logged
as [`docs/31`](31-factory-quirks.md) Q12–Q14, plus the *intended* command surface
(HR 11 reboot / HR 15 address move).

> **Scope / port note.** This audit is of the **EG4 Modbus register server** —
> the code that parses a dongle-format frame and serves functions
> `0x03/0x04/0x06/0x10`. The authoritative physical port for the external dongle
> is **UART5** ([`docs/wiring/ARM-UART5`](wiring/ARM-UART5-dongle/README.md)); the harness here
> drives the *same* server through the NVIC-vectored **USART3** framer (the
> known placeholder-collision path — see
> [`tests/arm_sim_modbus.py`](../tests/arm_sim_modbus.py) and
> [`docs/04`](04-modbus.md)). The parse/dispatch/apply chain audited below is the
> shared register server; the crash surface it exposes is port-independent.

## The receive & dispatch chain (what was audited)

Recovered statically (addresses are `ceaa-07xx_vE_260214`):

| stage | function | what it does |
|---|---|---|
| UART byte ISR | `sub_0801c0b0` → `sub_0801c022` (UART5 `0x40005000`); `sub_0801b9e4` (USART3 `0x40004800`) | reads one byte per RXNE |
| byte → ring | `sub_0801bf6a` (ring `0x2000bb80`) | enqueue, **capped at 200 bytes** |
| ring → frame | `sub_0801b6be` (frame struct `@0x2000a304`) | reassembles one EG4 frame |
| frame processor | `sub_0802d9b2` | length + CRC gate, stall-flush |
| function dispatch | `sub_0802d928` | `03/04`→read, `06/10`→write, else drop |
| read registers | `sub_0801ef68` → getter `sub_0801d48c` | serves `0x03/0x04` |
| write registers | `sub_0801f438` → setter `sub_0801f596` | serves `0x06/0x10` |
| comms task (owner) | `sub_0802e2f0` | runs the drain + processor each cycle |

### Frame assembly is bounded — no overflow

- **ISR ring (`sub_0801bf6a`, base `0x2000bb80`).** The write index is compared
  against `0xC8` (**200**) before every store; at the cap the index sticks and
  further bytes are **dropped**, never written past the ring. A byte flood loses
  bytes; it cannot overrun.
- **Frame assembler (`sub_0801b6be`, struct `@0x2000a304`).** Layout recovered:
  position `[+0x44e]`, declared length `[+0x452]`, a stall counter `[+0x456]`,
  and a "frame ready/busy" flag `[+0x458]`. Every byte store is guarded by
  `pos < 0x320` (**800**); at the cap the frame is abandoned. For `0x10` the
  declared length is computed as `byte_count_field + 9` — and the raw count byte
  is ≤ 255, so the declared length can never exceed ~264, well under the 800-byte
  buffer. **There is no path where a wire length field drives an unbounded
  copy.**
- **Processor gate (`sub_0802d9b2`).** A frame shorter than 7 bytes is skipped.
  CRC-16 (`0xA001`/`0xFFFF`) is recomputed over `frame[0 .. len-2]`
  (`sub_080160bc`) and compared to the trailing CRC word; a mismatch is dropped
  and counted. Only a length-valid, CRC-valid frame reaches dispatch.

### Read path caps the register count (`sub_0801ef68`)

- The register count is rejected when **≥ `0x80` (128)** → exception. So the
  response can hold at most 127×2 = 254 data bytes plus header — bounded.
- A func-`0x03` guard rejects `start+count` landing in **`[0x0FFF, 0x1388)`**
  (4095–4999) → exception.
- The per-battery window **5000–5015** (`0x1388–0x1397`) is served from a table
  at `0x20009790` indexed by `(reg-0x1388)/4` with **constant** divisor 4 and an
  explicit `<4` bound on both the quotient and remainder — no OOB.
- Every other register goes to the getter `sub_0801d48c`, which returns 0 for
  numbers it does not implement. **No read start/count combination faults.**

### Write path: `switch(regnum)` with a safe default (`sub_0801f596`)

- The setter is a subtract-and-branch cascade on the register **number**. A
  number that matches no case **falls through to a no-op** — an unknown or
  out-of-range holding register is silently ignored (the write still echoes),
  never an out-of-bounds store.
- Every `sdiv` in the setter uses a **constant** divisor (÷10, ÷2 for index
  math); none is derived from a register value, so **no divide-by-zero** is
  reachable from the wire. (And `SCB->CCR.DIV_0_TRP` is never set — address
  `0xE000ED14` is not referenced — so even a zero divide would return 0, not
  trap.)
- The echo/response is built **before** the per-register apply runs, so a
  rejected or unknown write still produces a well-formed reply.

## Dynamic confirmation (factory image, `tools/arm_sim.py` + `tests/arm_sim_modbus.py`)

Each case was injected as real bytes; "alive" = a follow-up `0x03` read of HR 21
still answers. Faults surface as `arm_sim` `RuntimeError("emu fault …")`.

| probe | result |
|---|---|
| `0x03/0x04` reads: start ∈ {0, 39, 40, 126, 999, 4095, 5000, 5016, 0x8000, 0xFFFF}, count ∈ {1 … 127} | all answered; **no fault** |
| read count ≥ 128 | exception (no fault) |
| read `start+count` in `[0x0FFF,0x1388)` | exception (no fault) |
| `0x06` write-single, every HR 0–260 × {0x0000, 0xFFFF} | echo or exception; **ARM alive**; unknown regs → exception |
| `0x10` write-multiple: `num=0xFFFF`, `nByte=0xFF`, `num=100/nByte=200`, mismatched count/bytes | all answered; **ARM alive** |
| extended function codes `0x21/0x23/0x31/0x33` | **silently dropped**, no reply, ARM alive — a dongle **cannot** drive the ARM into a firmware-update/erase path here |
| bad-CRC / 300-byte random garbage / `addr`+junk flood | dropped; channel **recovers** |
| truncated (half) frame then valid frame | next frame lost until the stall-flush fires (~10 comms-task cycles); **self-heals on an idle gap** — see Q13 |
| HR 11 all command bits incl. bit 7 (InvReboot), bit 1 (AlltoDefault) | echoed; **ARM alive** in-emulator (reboot did not manifest as a crash) — see Q14 |
| HR 15 (ComAddr) ← 2 | slave address moves to 2; reads on addr 1 stop, reads on addr 2 answer — self-lockout, by design |

## What this means for our firmware

- The defences above are **load-bearing** — keep them: the 200/800-byte caps, the
  `<128` register-count cap, the length+CRC gate, the register-count-independent
  response sizing, and the "unknown register ⇒ no-op/exception" default. Our
  `src/modbus/` engine already has CRC + count + span checks; this is the factory
  evidence that those are the right shape.
- The **differences** we must decide on (not copy by reflex) are the spec
  deviations in Q12–Q14 and the intended command registers (HR 11 / HR 15), which
  belong in a hardened slave behind an allow-list of writable registers.

## How to reproduce

```bash
python3 tools/hex2bin.py <factory>.hex reference/ceaa-07xx_vE_260214.bin
# then drive the register server with the dongle harness:
#   from arm_sim import ArmSim; from arm_sim_modbus import ModbusDongle
#   d = ModbusDongle(ArmSim("reference/ceaa-07xx_vE_260214.bin"))
#   d.read_holding(0, 41)      # 41 > 40  -> served (Q12)
#   d.write_single(11, 0x80)   # HR11 bit7 InvReboot (Q14)
```

Static disassembly of any function above: `python3 tools/disres.py <addr>`.
