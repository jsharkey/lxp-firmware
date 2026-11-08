# ARM UART4 ↔ (peer open — 2400-baud external bus)

**Status: open link.** What is known, pending identification. Research trail:
[`docs/25`](../25-modbus-register-spaces.md) (baud/role),
[`docs/16`](../16-arm-io-map.md) (pins),
[`docs/13`](../13-mppt-controller.md) (transceiver).

## Endpoints

| end | port | confidence |
|---|---|---|
| ARM "com" MCU | **UART4** `0x40004c00`, pins **PC10 TX / PC11 RX** | ✔ pins |
| peer | **unidentified** — an external meter (energy/CT) is the usual 2400 citizen | ? |

## Physical

- **RS-485, 2400 8N1, enabled** (UART4 `BRR 0x61a8`, RX+TX). Direction/DE
  candidate **PA15** (shared with UART5). The RS-485 DE toggle marks it an
  external multidrop bus.
- ISR IRQ52 `sub_0801c450`; GPIO driver `sub_0801c0b8` (between the UART4/UART5
  drivers).

## Framing / direction

Presumed EG4 Modbus family (same envelope as the other serial links), not
specifically decoded. Master/slave role not established.

## Open

- Peer identity (meter / CT / other) — needs a bus capture or the schematic.
- Confirm PA15 as the UART4 DE pin (shared with UART5).

## Reimplementation

None — only the USART3 driver exists under `src/uart/`. No binding yet.

## Factory RX buffer (ceaa-07xx)

Per-frame linear RX buffer **200 B** at `0x2000bd84` (`sub_0801c20c`, guard
`cmp #0xc8`; SOF byte `0x01`), ISR `0x0801c450`. Not implemented in ours. See
[`docs/47`](../47-factory-ram-static-breakdown.md).
