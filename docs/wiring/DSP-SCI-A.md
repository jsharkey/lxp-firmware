# DSP SCI-A → (peer unknown)

**Authoritative** for this link. Research trail:
[`docs/23`](../23-dsp-sci-a-crosscheck-handoff.md) (primary),
[`docs/29`](../29-safety-cpu.md).

A third DSP serial output, documented here mainly to **pin down what it is
not**: it is neither the ARM telemetry link nor the safety-CPU cross-check.

## Endpoints

| end | port | confidence |
|---|---|---|
| TI C2000 Control DSP | **SCI-A** (TXBUF ptr `DAT_0000aefc`) | ✔ exists (DSP image) |
| peer | **unknown** | ? |

## Physical

- **TTL, ~9600 baud** (SCI-A/C `BRR ≈ 0x186`; the DSP's only 19200 port is
  SCI-B).

## Framing

SCI-A is used for TX (`FUN_0009C3FD` feeds `SCIA_SCITXBUF`) but it sends
**unrelated bulk `LS4_RAM` 0x1F8-byte strided records** — a different protocol
from the type-1/`0x49` telemetry. It does **not** carry the ARM-facing config
or telemetry frame.

## Why this matters (the refutation)

USART2 was once suspected to be a direct DSP SCI (SCI-A). That is **refuted**:

- The DSP builds the type-1/BE telemetry frame (mode byte at `+4`, builder
  `FUN_00096EE8`) and transmits it on **SCI-B (= USART3)**, writing
  `DAT_0000aefe` (SCI-B TXBUF) — not SCI-A.
- SCI-A's traffic is the bulk `LS4_RAM` dump above.
- Baud decides it: the DSP has exactly one 19200 port (SCI-B), already = USART3.

So the DSP's three serial roles are: **SCI-A** = bulk `LS4_RAM` dump (peer
unknown), **SCI-B** = [`ARM-USART3`](ARM-USART3.md), **SCI-C** =
[`DSP-SCI-C`](DSP-SCI-C.md) (safety CPU).

## Open

- SCI-A's peer and the purpose of the `LS4_RAM` dump.
- Both DSP images on hand expose one 19200 port; a dedicated SCI-A telemetry TX
  on an un-analyzed MPPT/3-phase DSP build cannot be excluded outright, but is
  absent from both images.
