# Firmware architecture — cooperative scheduler + interrupt-driven I/O

A design-decision record for the open reimplementation, grounded in what the
factory ARM image actually does.

## The factory is *not* an RTOS

Despite the battery BMS chip ([`docs/20`](20-battery-bms-firmware.md)) using a
named-timer RTOS, the **ARM com-MCU** does not:

- `SVCall` (`0x08002892`) and `PendSV` (`0x08002896`) are **empty `bx lr`
  stubs** — no context switch, no task stacks. (FreeRTOS uses SVC to launch the
  first task and PendSV to switch; both are no-ops here.)
- There are **zero** `FreeRTOS`/RTOS strings in the image.
- What drives it is a **cooperative, SysTick-ticked super-loop**: `SystemInit`
  → a real `SysTick` handler → a scheduler (`sub_0803e4c8`) that registers
  periodic run-to-completion callbacks (`sub_0801c11c` DSP comms, `sub_08015094`
  TX, `sub_0802a760` battery-CAN, `sub_080140e8` comms).

**Decision: match it.** The ARM is a comms/HMI/supervisor MCU; the hard
real-time power loop is on the TI DSP. A cooperative super-loop is simpler to
read, debug and contribute to, has no inter-task data races by construction, and
needs one stack. We do not add an RTOS. (Because each task is already
run-to-completion, a future subsystem that genuinely needs to block can become a
single RTOS task later without reworking the rest.)

## I/O model — match the factory per peripheral

The factory does **not** treat its links uniformly, and neither do we:

- **USART3 is fully interrupt-driven** (vector 55 / IRQ 39 — the only NVIC-vectored
  UART; `RXNEIE` set, bytes taken in the ISR, TX shifted out under `TXEIE`). We
  match this: RX/TX ring buffers serviced from `USART3_IRQHandler`.
- **CAN1 is polled** (`sub_08005758` → ring `0x200051ac` → parser `sub_0802a760`;
  all four CAN IRQ vectors are the shared default handler). We match this too —
  the battery bus is read from a scheduler poll, not an interrupt.

Either way the task layer stays cooperative: **interrupts (where used) only move
bytes into a ring; the main loop drains and processes them.**

| piece | file | notes |
|---|---|---|
| lock-free SPSC ring | [`include/inv/ringbuf.h`](../include/inv/ringbuf.h) | power-of-two, one producer + one consumer, no critical section on single-core M3; host-tested (`tests/test_ringbuf.c`) |
| USART3 driver (IRQ) | [`include/inv/uart.h`](../include/inv/uart.h), `src/uart/uart3.c` | `USART3_IRQHandler`: RX→ring; TX ring under `TXEIE`; RS-485 DE released on `TC` via weak `uart3_set_de()` |
| Modbus port | `src/modbus/modbus_port.c` | drains the UART RX ring, reassembles RTU frames by the inter-char gap, queues the reply for background TX |
| CAN1 port (polled) | `src/can/can_port.c` | `can_port_poll()` drains FIFO0; `can_port_send()` into a mailbox; decoder in `src/can/bms_can.c`, wired in `main.c` |

The USART3 ISR overrides the startup file's weak vector alias (verified: vector
`0xdc` → `USART3_IRQHandler`), so no startup edit is needed. `make` builds the
firmware; `make test` runs the ring tests.

### Why interrupt-driving USART3 is a safe deviation

- Task **timing/cadence is unchanged** — the ISR does no work beyond a ring push,
  so the DSP-link and scheduler contracts hold.
- RX is **robust to bursts**: a byte can't be missed while a task runs long.
- No new concurrency hazards: an SPSC ring needs no locks on a single core.

### Why CAN stays polled

The factory polls CAN1 (no RX IRQ), and the sim harness (`tests/arm_sim_can.py`)
models a polled reader. Interrupt-driving CAN RX is a legitimate option — the
same ring pattern applies — but it is a real deviation from the factory for this
bus and would require the CAN sim harness to deliver the FIFO0 IRQ (the
polled-vs-IRQ issue that commit `e76ad44` solved for USART3). Left polled until
there's a reason to change it.

## Not yet decoded / TODO

- **CAN bit timing / baud.** `src/can/can_port.c` assumes **500 kbit/s** —
  `docs/20` lists the bus baud as TBC and the factory `CAN_BTR` (in
  `sub_08022660`) was not decoded. Confirm against hardware.
- **RS-485 DE/RE pin** for USART3 — provide `uart3_set_de()` in a board file once
  the pin is known (`docs/16`).
- **Full battery-frame decode** — `bms_can.c` decodes the core IDs; the rest are
  specified in [`include/inv/bms_can_map.h`](../include/inv/bms_can_map.h)/`docs/20`.
- **(Optional) interrupt-driven CAN RX** — deviates from the factory (which polls)
  and needs the CAN sim harness to deliver the FIFO0 IRQ; see "Why CAN stays
  polled".
- A small **cooperative scheduler** table (`{period, handler}`) to formalize the
  super-loop, mirroring `sub_0803e4c8`.
