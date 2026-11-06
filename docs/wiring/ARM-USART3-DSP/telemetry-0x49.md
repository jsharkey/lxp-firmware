# DSP `0x49` telemetry on USART3 — **not consumed by the ARM** (T09)

> **ARM USART3 RX, the return direction of the ARM↔DSP wire.** See the
> [index](fields.md), the [`README`](README.md) and
> [`bootloader-21_23`](bootloader-21_23.md).

> **Correction (T09, docs/39).** An earlier version of this file stated that the
> ARM parses the DSP's `0x49` type-1 telemetry frame on USART3 (ARM parser
> `FUN_08025ab8`, RX state machine `FUN_0801bb0e` "keying on `0x49`"). **That was
> wrong — it attributed the USART2 safety-CPU `0x49` path to USART3.** The ARM's
> USART3 receive path is a **Modbus-slave + DSP-bootloader demux**; a `0x49`/type-1
> frame is **rejected**. The `0x49` the ARM actually consumes arrives on **USART2**
> from the safety CPU (docs/22, docs/30, docs/33). Evidence below.

## What the ARM's USART3 RX actually does

The USART3 receive ISR assembles a frame byte-by-byte and accepts it only if the
**first byte matches this device's address** (or `0` = broadcast) and the
**second byte is a known function code**:

| 2nd byte (func) | class | consumer |
|---|---|---|
| `0x03` `0x04` `0x06` `0x10` | **Modbus slave** request | the register engine (ARM answers as slave) |
| `0x21` `0x22` `0x23` | **DSP bootloader** / firmware update | [`bootloader-21_23`](bootloader-21_23.md) |
| anything else (incl. `0x01`, the type byte of a `SOF 0x49` frame) | **rejected** — assembler index reset | — |

So a `0x49` frame fails twice over: `0x49` as the first byte is not our address
(dropped at index 0), and `0x01` as a second byte is not a function code (resets
the assembler). The frame never assembles, so **the ARM does not consume DSP
`0x49` telemetry on USART3.**

### Evidence (image `com_flat.bin`, 260214-family App @ `0x08005000`)

Static (App vector table + `tools/disres.py`) and dynamic (driving the real byte
handler in `tests/dsprx_contract.py`):

| | **USART3** (ARM↔DSP) | **USART2** (safety CPU) |
|---|---|---|
| IRQ → ISR | IRQ39 → `0x0801c774` | IRQ38 → `0x0801ca94` |
| peripheral base | `0x40004800` | `0x40004400` |
| RX drain | `sub_0801c6e0` | `sub_0801c9ec` |
| byte handler | **`sub_0801c3e6`** (frame buffer `0x20007490`, index `+0x44e`) | `sub_0801c992` + `sub_0801c808`/`sub_0801c898` (buffer `0x20009048`) |
| checks `SOF 0x49`? | **no** — the func byte is only ever compared to `03/04/06/10/21/22/23` | **yes** — `cmp r0, #0x49` at `0x0801c82c` in `sub_0801c808` |
| `0x49` parser | — (frame rejected) | `FUN_08025ab8` reads the USART2 buffer `0x20009048` |

- The address gate reads this device's address from `0x2000a0d8 + 0x9b`
  (`sub_0801c3e6` @ `0x0801c418`); the func dispatch is the `cmp #3/#4/#6/#0x10`
  then `#0x21/#0x22/#0x23` chain, every other value doing `strh 0, [buf,#0x44e]`
  (reset). Full listing: `python3 tools/disres.py 0x0801c3e6 --img
  reference/com_flat.bin --sym reference/symbols.csv`.
- Caller scan: `sub_0801c3e6` is BL-called **only** from `0x0801c714` (inside the
  USART3 drain `sub_0801c6e0`); the `0x49` detector `sub_0801c808` **only** from
  `0x0801ca32` (inside the USART2 drain `sub_0801c9ec`). The two wires have
  entirely separate RX handlers.
- `FUN_08025ab8` (the function the old doc called "the telemetry parser") loads
  `0x20009048` — the **USART2** frame buffer — not the USART3 buffer `0x20007490`.
  Whatever its exact role, it is on the USART2 side, not reachable from the USART3
  ISR chain.

Dynamic oracle: `tests/test_dsp_rx.py` feeds the real `sub_0801c3e6` the first two
bytes of each candidate frame and checks whether the assembler advances to index
2 (accepted) or stays at 0 (dropped): Modbus and bootloader funcs assemble, a
`0x49`/`0x01` frame does not — and our `inv_dsp_rx_classify()` agrees on every
vector.

## Where the DSP's telemetry actually goes

The DSP *does* build a `0x49` telemetry frame (DSP-side builder `FUN_0009DD14` →
`FUN_0009D358`, writing SCI-B TXBUF — see [`README`](README.md) "Key functions").
But on the ARM, the **authoritative operating state, core input registers,
measurements and fault/warning words are decoded from the safety CPU's `0x49`
frame on USART2** (`sub_0801c808` SOF detect → USART2 buffer `0x20009048` →
telemetry bank; [`ARM-USART2-safety`](../ARM-USART2-safety.md),
[`docs/33`](../../33-usart2-telemetry-bank.md), [`docs/22`](../../22-arm-dsp-core-split.md)).

**Open:** since the ARM's USART3 RX provably rejects `0x49`, the DSP's own `0x49`
on SCI-B is either not wired to USART3 RX in hardware, or is delivered and
dropped. Either way it is not an ARM telemetry source. Logged as a candidate quirk
in [`docs/31`](../../31-factory-quirks.md) (Q10).

## Reimplementation (ours)

- Core (pure, host-tested): [`include/inv/dsp_rx.h`](../../../include/inv/dsp_rx.h)
  + [`src/dsp/dsp_rx.c`](../../../src/dsp/dsp_rx.c) — `inv_dsp_rx_classify(first,
  func, dev_addr)` → `{REJECT, MODBUS, BOOTLOADER}`, mirroring `sub_0801c3e6`'s
  framing decision. Host test: [`tests/test_dsp_rx.c`](../../../tests/test_dsp_rx.c).
- Port (USART3 service): [`src/dsp/dsp_rx_port.c`](../../../src/dsp/dsp_rx_port.c)
  `inv_dsp_rx_poll()` drains USART3 RX, assembles a frame on the inter-frame gap,
  classifies it, serves a Modbus request against the register map and replies on
  USART3 (the DSP polls the ARM here), recognises a bootloader frame (T18), and
  drops everything else. Wired into [`src/main.c`](../../../src/main.c).
- Common spec (factory oracle vs ours): [`tests/test_dsp_rx.py`](../../../tests/test_dsp_rx.py)
  + [`tests/dsprx_contract.py`](../../../tests/dsprx_contract.py) (`make test-sim`).
