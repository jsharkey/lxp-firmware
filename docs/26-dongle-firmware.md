# The external "dongle" firmware — what it proves about the ARM UART

> **Authoritative wiring:** the UART5↔dongle link is distilled in [`docs/wiring/ARM-UART5.md`](wiring/ARM-UART5.md). This doc remains the dongle-firmware analysis.

Status: **analyzed from the attached dongle image** (`abbc426d-E_V2_12.bin`).
This is the monitoring **dongle** that plugs into the inverter's external
comms port — the far end of the "external RS-485 / Modbus" link in the
[docs/16 block diagram](16-arm-io-map.md). The question it was brought in to
settle: **which ARM UART is the dongle on?** (the one place docs/04 and docs/16
disagreed — see "Resolving the contradiction" below).

> **Up front:** the dongle is a **different MCU** (an Espressif ESP32‑C3,
> RISC‑V), so its firmware can never *name* an STM32 pin. What it does do is
> pin down the **medium, role, and framing** of the link — and those, combined
> with the ARM‑side RE already in hand, leave exactly one ARM UART that fits,
> and rule out the other candidate. That is the "extra hint," and it is
> decisive by elimination.

## What the image is

Parsed from the ESP‑IDF v2 application header (`tools`-free, `python3 -I`):

| field | value |
|---|---|
| chip | **ESP32‑C3** (chip_id 5, RV32IMC) |
| project | `esp32_dongle` |
| app version label | `E_V2_12` (the filename) / descriptor version `1` |
| built | **Feb 5 2026 17:56:50**, IDF `v4.4.5-dirty` |
| segments | DROM `.rodata`@`0x3c0e0020`, IROM `.text`@`0x42000020` (857 KB), IRAM, DRAM |
| framework | **HIDO** IoT SDK (`HIDO_NULL`, `hido-iot.com`) — a white‑label datalogger platform |

So it is a **Wi‑Fi + BLE datalogger**: BLUFI provisioning, HTTPS OTA
(`esp_https_ota`), a `TCPClientApp` that uploads to a **configurable** upstream
server (`"Server:%s,%u"`, with a heartbeat/keepalive), and a dedicated
**RS‑485 service** that talks to the inverter. Layered source paths survive in
`.rodata`: `main/APL/RS485App.c`, `main/FML/RS485Service.c`,
`main/FML/UartService.c`, `main/APL/WIFIApp.c`.

## What the RS‑485 link looks like (proven from the dongle's own code)

`RS485Service_Init(pstInit)` at **`0x4200c48c`** brings the inverter link up
through the standard ESP‑IDF UART driver. Disassembled (capstone RV32), the init
sequence and its own assert strings are unambiguous:

```
uart_driver_install(port, rxbuf*2, 0, 0, NULL, 0)
uart_param_config(port, &uart_config)      ; data_bits=3 (8), parity=0 (N), stop_bits=1 (1)  => 8N1
uart_set_pin(port, TXD, RXD, RTS, CTS=-1)  ; RTS used as the driver-enable (DE) line
uart_set_mode(port, UART_MODE_RS485_HALF_DUPLEX)   ; <-- hardcoded (li a1,1)
uart_set_rx_timeout(port, rx_timeout)
```

Two facts matter for us:

1. **The link is RS‑485 half‑duplex.** `uart_set_mode(..., 1)` is hardwired to
   `UART_MODE_RS485_HALF_DUPLEX` (the matching assert string
   `"uart_set_mode(pstInit->m_i32PortNum, UART_MODE_RS485_HALF_DUPLEX)"` is at
   `0x3c0e7aec`, referenced from `0x4200c5b0`). The dongle drives a **DE/direction
   line** (the UART's RTS) and turns the bus around per transaction — the
   signature of a shared RS‑485 bus with a direction‑controlled transceiver, not
   a point‑to‑point TTL inter‑chip link.

2. **The dongle is the bus master; the inverter is the slave.** It is a
   datalogger: it *polls* the inverter (request → `RS485Recv Timeout` → parse),
   then forwards the data to its cloud server. The RS‑485 side only ever
   initiates reads; it never serves a register map. So whatever ARM UART it
   lands on, **the ARM must behave as the Modbus *slave* on that link.**

The **baud is not hard‑coded** — it is a config field (`pstInit->m_u32BaudRate`,
loaded from `pstInit+0x14` into `uart_config.baud_rate`), set at runtime from the
persisted config/NVS (there is a `"Config struct mismatch: magic/ver"` blob).
The image carries a whole **baud table** (`0x42003240…`, 2400 → 921600), i.e. the
dongle is field‑configurable to match whatever the inverter port runs; the only
baud *written into code* is `115200`, and that is the **debug console**, not the
inverter link. So the dongle can't be used to prove a specific baud number — it
just has to be set to the inverter's rate. On this unit the ARM configures
**UART5 at 9600 8N1** (post‑boot `USART_BRR` read,
[`docs/25`](25-modbus-register-spaces.md)/[`docs/13`](13-mppt-controller.md)), so a
dongle on UART5 is provisioned to 9600.

> **Baud discrepancy to flag (spec 19200 vs observed 9600).** The public EG4
> 18kPV Modbus spec and [`docs/04`](04-modbus.md) cite **19200 8N1** for the
> external Modbus, and 19200 is the rate the ARM runs on **USART3** (and the rate
> our skeleton's USART3‑bound Modbus uses). But the ARM configures **UART5 at
> 9600**, and UART5 is where the dongle handler lives (docs/08). Two readings fit:
> this model's external dongle port simply runs 9600 (the dongle's configurable
> baud set to match), or the spec's 19200 is nominal/other‑model. The dongle
> firmware can't settle it (its baud is config‑driven, not a literal); a **bus
> capture** on the physical dongle port would. Either way it does **not** move the
> dongle back to USART3 — the register handler is on UART5 regardless of baud.

> **The dongle is a transparent byte conduit, not a register-aware poller.** Its
> RS-485 layer is a generic pipe — `RS485Service` → `SendBytes(port, buf, len)`
> (+ `uart_wait_tx_done`) and a `UartRxTask` — relaying **opaque** EG4-Modbus
> frames between its cloud/BLE side and the inverter; `RS485App.c` is mostly
> logging and queue plumbing, with no on-device register/function-code dispatch.
> Consequence: the dongle can only surface data the ARM already serves as a
> register — it cannot reach anything the ARM leaves in private RAM. That is why
> the per-battery BMS stats carried on CAN never come out this way — see
> [`docs/34`](34-multi-battery-can.md).

## Mapping that onto the ARM

From [docs/16](16-arm-io-map.md) and [docs/05](05-dsp-link.md), the ARM drives
five UARTs; three of them carry the EG4 Modbus‑family framing. Match each
against the two things the dongle firmware just proved — **external RS‑485** and
**ARM = slave**:

| ARM UART | peer / role (from ARM RE) | external RS‑485? | ARM is slave? | = dongle? |
|---|---|---|---|---|
| **UART5** `0x40005000` (PC12/PD2, DE≈PA15) | external **dongle** port | **yes** | **yes** (answers standard reads) | **✅ matches** |
| USART3 `0x40004800` (PB10/PB11) | **DSP** (C2000 SCI‑B): ARM **pushes** config + `0x21/0x22/0x23` bootloader; DSP is the slave | no (internal inter‑chip) | **no — ARM is the master here** | ❌ ruled out |
| USART2 `0x40004400` (PA2/PA3) | DSP→ARM telemetry (inbound) | no | n/a (receive‑only link) | ❌ |
| USART1 / UART4 | meter / console / ? (unpinned) | unknown | unknown | — |

Only **UART5** satisfies both conditions. The external‑RS‑485 requirement knocks
out the internal DSP/telemetry links; the master/slave direction specifically
knocks out **USART3**, which the ARM drives *as the master* toward the DSP.

This is not just elimination — the ARM‑side RE has the positive locator too:
[`docs/08`](08-arm-dsp-config-protocol.md) finds the dongle's standard‑Modbus
register handler `sub_0802afe2` as a scheduler task on **UART5 `0x40005000`**
(RX buffer `0x20008ca4`), serving `0x03/0x04/0x06/0x10` out of the central
settings store `0x20009854`. The dongle firmware's "RS‑485 master, ARM = slave"
signature is exactly what that handler is the ARM end of. The ARM's one
serializer `sub_0803373c` is dual‑mode (flag `0x2000aa0b` bit 0): **LE + 10‑byte
SN** to the dongle, **big‑endian + block‑tagged** to the DSP — so the shared
EG4 frame family is real, but the dongle leg of it is UART5.

## Resolving the docs/04 ↔ docs/16 contradiction

The repo carried a genuine inconsistency the dongle image now settles:

- The **reimplementation and [docs/04](04-modbus.md)** put the Modbus‑RTU slave
  on **USART3** (`src/modbus/modbus_port.c`, `src/uart/uart3.c`) — because USART3
  is the factory's only NVIC‑vectored UART and speaks the EG4 Modbus frame, so it
  *looked* like the external Modbus port. docs/04 even left the open TODO
  *"Confirm from schematic: USART3 = RS‑485 Modbus port (vs DSP link)."*
- The later ARM‑side RE ([docs/16](16-arm-io-map.md), [docs/22](22-arm-dsp-core-split.md),
  [docs/23](23-dsp-sci-a-crosscheck-handoff.md)) concluded **USART3 = DSP control
  link** and **UART5 = external dongle**, and [docs/05](05-dsp-link.md)'s dynamic
  RE found that **USART3's frame path only deep‑processes the extended
  `0x21/0x22/0x23` commands** (the DSP bootloader/config push) — the standard
  `0x03/0x04/0x06/0x10` register serving a datalogger needs is a *separate*
  handler that was never pinned to USART3.

The two sides share the **same EG4 Modbus envelope** (addr · func · 10‑byte SN ·
body · CRC‑16), which is exactly why the same framing turns up on both the
internal DSP link and the external dongle link — and why the reimplementation
reasonably but mistakenly anchored "Modbus" to the vectored USART3.

**The dongle firmware breaks the tie decisively: it is an RS‑485 *master*
datalogger.** A master cannot sit on USART3, where the ARM is itself the master
(two masters can't drive one bus), and USART3 is an on‑board inter‑processor
link, not an external RS‑485 connector. The dongle must therefore sit on the ARM
link where the ARM is the **RS‑485 slave serving the standard register map** —
i.e. **UART5**, confirming docs/16. The "Modbus‑on‑USART3" label in the code is
really the **DSP control link**; the external Modbus the dongle speaks is on
**UART5**.

## Reconciling docs/25 (which had said "the slave is USART3")

[`docs/25`](25-modbus-register-spaces.md) §1 earlier reached the opposite
tentative call — that the one EG4‑Modbus register slave is **USART3** and that
"UART5 at 9600 is unlikely to be the dongle." Both of its arguments fall to the
evidence here, and docs/25 has been corrected to match:

- **"EG4 is 19200, UART5 is 9600, so UART5 isn't the dongle."** Void — the
  dongle's baud is **field‑configurable** (§ above); it is simply set to UART5's
  9600. Baud is not a discriminator.
- **"A black‑box `0x03` probe replies only on USART3, not UART5."** That is a
  false negative: the UART5 dongle handler (`sub_0802afe2`) is a **gated
  scheduler task** that a cold probe can't start — docs/08 flags exactly this
  ("cold runs don't build a response"). The USART3 reply the probe *did* get is
  the ARM's dual‑mode bridge serializer in its LE+SN mode, and/or an artefact of
  our own reimplementation wiring Modbus to USART3 (docs/04) — which is also why
  the `tests/arm_sim_modbus.py` harness hooks USART3. None of that makes USART3
  the dongle port.

So the dongle firmware doesn't just add a vote for UART5 — it removes the only
concrete objections that stood against it.

## Conclusion

- **The dongle is on ARM UART5** (`0x40005000`, TX `PC12` / RX `PD2`, direction/DE
  candidate `PA15`), as an **RS‑485 half‑duplex** bus with the **ARM as Modbus
  slave**, **8N1**, at UART5's configured **9600** (docs/25/13) — note the
  spec‑vs‑observed baud discrepancy flagged above (spec cites 19200; UART5 reads
  9600).
- **USART3 is *not* the dongle** — it is the ARM→DSP (C2000 SCI‑B) control /
  bootloader link that happens to reuse the same EG4 frame family.
- This is **conclusive on medium, role, and by‑elimination which UART**, within
  the ARM‑side pin map already recovered. The one thing an ESP32 image cannot
  itself supply is the STM32 pin number; UART5 = PC12/PD2 still rests on the
  ARM AF map (docs/16).

### The clean closing experiment (ARM side, no schematic needed)

To nail the pin from firmware alone, run the committed Unicorn harness against
the ARM image: inject a crafted EG4 `0x04` (read‑input) frame into **each** UART
RX handler in turn and watch for the pair of behaviours this doc predicts for the
dongle link — (a) the handler **responds as a slave** (emits a register‑read
reply) and (b) it **toggles an RS‑485 DE GPIO** (the `PA15` candidate) around the
TX. The UART that does both is UART5. USART3, by contrast, will only react to
`0x21/0x22/0x23` and drives no external DE line. That experiment, plus this
dongle analysis, closes docs/04's TODO and docs/16's "map UARTs→peers" item for
the dongle.

## Reproduce

The image is untrusted data; it was analyzed read‑only, with the interpreter
isolated (`python3 -I`) and the path passed as an argument. The analyzer is
committed as [`tools/dongle_fw.py`](../tools/dongle_fw.py) (the image itself is
a proprietary factory binary and is not committed — point the tool at your copy).
RV32 disassembly needs `capstone` built with the RISC‑V backend (`pip install capstone`).

```
# header / segments / app descriptor (chip, project, build date, IDF version)
python3 -I tools/dongle_fw.py  abbc426d-E_V2_12.bin
# RS-485 init disassembly — the hardcoded UART_MODE_RS485_HALF_DUPLEX + 8N1 + pins
python3 -I tools/dongle_fw.py  abbc426d-E_V2_12.bin --disasm 0x4200c480 0x4200c620
# the RS485-half-duplex assert string and the code that references it
python3 -I tools/dongle_fw.py  abbc426d-E_V2_12.bin --str HALF_DUPLEX
# every baud-rate immediate (shows the configurable baud table; no fixed inverter baud)
python3 -I tools/dongle_fw.py  abbc426d-E_V2_12.bin --bauds
```
