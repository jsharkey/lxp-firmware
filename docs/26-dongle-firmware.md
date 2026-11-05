# The external "dongle" firmware — what it proves about the ARM UART

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
just has to be set to the inverter's rate (the EG4/Luxpower convention, and the
value our docs/04 recovered on the ARM side, is **19200 8N1**).

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

## Conclusion

- **The dongle is on ARM UART5** (`0x40005000`, TX `PC12` / RX `PD2`, direction/DE
  candidate `PA15`), as an **RS‑485 half‑duplex** bus with the **ARM as Modbus
  slave**, **8N1**, baud set to the inverter's rate (19200 by EG4 convention).
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
