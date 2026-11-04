# GPIO test harness — assert firmware behaviour against the oracle

`tools/arm_sim.py` is a GPIO-instrumented STM32F103 emulator (Unicorn) that runs
**both** firmwares through one API:

- **our firmware** — `build/firmware.bin` + symbols from `build/firmware.elf`;
- **the factory image** — `reference/com_flat.bin` + `reference/symbols.csv`.

So we can capture a behaviour from the factory image (the **oracle**) and assert
our reimplementation reproduces it, pin for pin, as features land.

## What it models

- Cortex-M3 + flash @`0x08000000` + 64 KB RAM @`0x20000000`.
- **GPIO ports A–E** (the ports this MCU uses, per
  [`docs/16`](16-arm-io-map.md)). Writes to `BSRR`/`BRR`/`ODR` update a per-port
  **output shadow latch** and are logged; reads of `IDR` return whatever
  `set_input()` injected. Pins are addressed by their docs/16 names (`"PB7"`,
  `"PC8"`, …), with a few functional aliases (`"KEY1"`, `"RELAY_TRANSFER_A"`, …).
- **Clock / UART readiness**: `RCC_CR`/`RCC_CFGR` report HSE/PLL ready and
  `SWS==SW`, and `USART_SR` reports `TXE|TC`, so `SystemInit` and TX loops don't
  spin forever — `run_reset()` can boot our firmware through its init.

It is a behavioural harness, not a full SoC: no real timers/DMA/interrupts, no
analog. It is for *observable GPIO* contracts.

## API

```python
from arm_sim import ArmSim
sim = ArmSim.factory()                 # reference/com_flat.bin + symbols.csv
sim = ArmSim.ours()                    # build/firmware.{bin,elf}
sim = ArmSim("path.bin", symbols_dict) # explicit

sim.set_input("PB7", 1)                # inject an external input level (IDR bit)
sim.clear_drives()
# boot the image's own loop (black box) and stop at the expected edge:
driven = sim.run_until_output("PB7", level=1, max_insn=200_000)
sim.run_reset(max_insn=300_000)        # or run a fixed budget from reset
sim.call("mb_port_init", (cfg_ptr,))   # or call one function, by symbol/address

# warm once, then branch each case from an identical, hermetic copy:
sim.run_until_input_read("PB7")        # boot up to the first time PB7 is sampled
warm = sim.snapshot()                  # CPU + all memory + GPIO shadow
sim.restore(warm); sim.set_input("PB7", 1); sim.run_until_output("PB7", 1, reset=False)

sim.enable_systick(20_000)             # drive tick-gated logic (see below); off by default

sim.get_output("PB7")                  # current driven level (shadow latch)
sim.was_driven("PB7", level=1)         # was it driven (to a level) since clear?
sim.r32(addr) / sim.bit(addr, n)       # peek RAM (status words, flags)
```

`run_reset()` finds the vector table itself (`vector_base()`), so our
monolithic image (@`0x08000000`) and the factory App that sits above an absent
bootloader (@`0x08005000`) both "just boot".

### Warm once, clone per case (speed)

Booting the factory to where its loop first touches a pin costs ~640k
instructions; paying that per test case is the dominant cost. Instead the test
**warms once** — `run_until_input_read("PB7")` boots up to the first PB7 sample
(boot is input-independent, so the warm point is identical whatever level we
test) — takes a `snapshot()` (CPU context + every mapped region + the GPIO
shadow), and `restore()`s it before each case. Each case resumes
(`run_until_output(reset=False)`) and finishes in a few hundred instructions.
Restores are hermetic: order-independent and repeatable (verified).

> **Why not warm to full "steady state"?** By default this harness has no timer,
> so a firmware's cooperative scheduler only advances during boot. We warm only
> up to the first sample of the pin under test, never past it. (For PB7 that is
> also the *right* point: see the SysTick note below — its sampler turned out to
> be a boot-time one-shot, so there is no later "steady state" for it anyway.)

## SysTick injection (tick-driven behaviours)

`sim.enable_systick(interval)` fires the **SysTick interrupt** every `interval`
emulated instructions: the run proceeds in chunks and, between them, the SysTick
vector handler is invoked with full register save/restore (a precise interrupt at
a chunk boundary). Both firmwares arm SysTick with `TICKINT`, so without this
their 1 ms tick counters never advance and all tick-gated logic — the scheduler,
periodic tasks, our firmware's `g_ticks`-gated render/DSP cadence — freezes after
boot. `test_systick_advances_tick_counter` checks our `g_ticks` advances with it
on and stays 0 with it off. It is **off by default** (keeps non-tick tests fast).

> **Finding:** injecting SysTick did *not* make the factory re-run the **PB7**
> sampler — so that sampler is a boot-time one-shot (a strap/config read), not a
> periodic task. That is why the PB7 test uses warm+snapshot, not ticks. SysTick
> is the tool for the genuinely periodic behaviours (the IR_STATE-driven relays,
> the DSP push cadence); turn it on when testing those.

## Booting the factory further (toward the relay app-loop)

The power-path **relays** (docs/18) are driven from the factory's main control
loop (`sub_0801b3dc`), which is reached only after a long hardware-dependent
boot. Getting there turned up two things worth recording:

- **The com MCU is an M4-class core, not a Cortex-M3.** The factory executes
  ARMv7E-M DSP instructions (`smlabb`, `sdiv`, …) as real code, which fault under
  a Cortex-M3 model. With STM32F1-compatible peripherals + an M4 core, it is
  almost certainly a **GD32F303-style F1 clone**. The harness now uses an M4
  model (our own M3-built firmware still runs, M4 being a superset). *(Worth
  reconciling with docs/01's "STM32F103 / M3" identification.)*
- Boot polls a chain of **peripheral-ready** signals that a bare sandbox leaves
  at 0: the harness now fakes **RCC_BDCR LSERDY** (RTC crystal), **RCC_CSR
  LSIRDY**, **RTC_CRL RSF/RTOFF**, and **SPI1/2 SR TXE|RXNE** — the same class as
  the existing HSE/PLL/USART fakes. These advance boot from an early LSE spin to
  deep into SPI device bring-up.

**An SPI NOR config-flash is modelled.** Past the ready flags, boot does real
SPI transactions against an external **config/settings flash** on SPI1 (opcodes
`0x06` WREN, `0x05` RDSR, `0x03` read, `0x02` program, `0x20/0x52/0xd8` erase,
`0xc7` chip-erase — classic SPI NOR). `sim.attach_spi_flash()` provides a
RAM-backed `SpiNorFlash` (starts erased) so these complete. With it, boot gets
**all the way through init**: it reaches the `cpsie i; b .` idle at `0x0801c47c`
— i.e. the firmware is **interrupt-driven**; the main thread finishes init and
idles, and all periodic work runs from ISRs.

**The factory runs a preemptive RTOS.** With SysTick injected, the SysTick ISR
runs the software-timer scheduler (`sub_0802f50c`) — but the relay task
(`sub_0802e2f0` → `sub_0801b3dc`, an *infinite loop*, not a returning callback)
still never runs. The reason: **PendSV (`0x0801c490`) is a classic RTOS context
switcher** (`MRS r0,PSP; stmia {r4-r11}` → save task context to its TCB, load the
next). So `sub_0801b3dc` is a *task* that runs on its own PSP stack, switched in
by PendSV; the first task is launched by the first SysTick→PendSV after `cpsie`
(no SVC). The main thread idles at `cpsie i; b .` and the task only gets the CPU
via that context switch.

**A Cortex-M exception engine (`enable_rtos()`) — built, and it works.** Unicorn
emulates the CPU but not the exception machinery the switch relies on, so
`enable_rtos()` models it: exception **entry** hardware-stacks
`{r0-r3,r12,lr,pc,xpsr}` on the active stack and vectors to the handler on MSP;
**EXC_RETURN** (Unicorn raises `UC_HOOK_INTR` when execution branches to
`0xFFFFFFFx`) unstacks and resumes on MSP/PSP; **SysTick** is injected between
run-chunks and **PendSV** is tail-chained whenever a handler returns to thread
with `PENDSVSET` pending. The firmware's own SysTick/PendSV handlers then do the
real scheduling and the FreeRTOS-style context switch (`mrs/msr psp` + `{r4-r11}`,
using Unicorn's native MSP/PSP banking). Verified end-to-end on the factory
image: SysTick fires as exceptions, PendSV runs, and the engine **context-switches
to a real PSP task** (`0x08030010`).

**What still blocks the relay task specifically (honest).** With the engine
running, the firmware only schedules a minimal task set in the harness (an
idle-like spinner, plus one garbage TCB whose stacked PC is 0 — a sign of
*incomplete init*). The control/relay task (`sub_0801b3dc`) is **never created /
made ready**, because task creation is gated behind init we have not satisfied
(the config-flash *contents* the firmware validates, and likely the DSP link).
So running the relays end-to-end through the scheduler needs that init gate
resolved, not more exception-engine work. The engine guards against the invalid
switch (it halts rather than faulting). **Validating the relay behaviour does not
need any of this** — the relay tests below run the factory's real relay code
directly with seeded state.

### The relay parity tests (target-specific: shared contract, per-image drive)

The relays can't be reached as a pure black box: the factory drives them from an
RTOS task the harness doesn't schedule (per above), so there is no GPIO input to
inject that makes the loop drive them. Instead each firmware is exercised through
its *own* drive path, with seeded state — the same state the RTOS task would act
on — and both are held to **one shared contract** (`tests/arm_sim_contract.py`).
Because the identical spec passes on each side, the factory oracle and our
reimplementation are proven to agree without a test that compares the two
directly. These are **target-specific**, so they live outside the common file:

- `tests/test_arm_sim_self_only.py` — our firmware, by symbol (`src/relay.c`);
- `tests/test_arm_sim_factory_only.py` — the factory image, by address.

**1. Working mode → run-enable relay** (`test_relay_follows_working_mode`): PC6
is closed iff the inverter is in a running operating mode. Factory: seed
`IR_STATE` (`0x2000d0e4+0xa0`), invoke `sub_08016ec6`; ours: `relay_set_mode()` +
`relay_poll()`.

| IR_STATE | | PC6 |
|---|---|---|
| `0x00/0x01/0x02` | standby / fault / programming | 0 (open) |
| `0x04/0x10/0x40/0xC0` | any running state | 1 (closed) |

**2. Manual/AutoTest override** (`test_relay_override_drives_transfer_pins`): the
grid-protection self-test (docs/18) drives the AC transfer relays directly.

| command | manual? | PA12 | PB3 |
|---|---|---|---|
| bit1=0 bit0=0 | yes | 0 | 0 |
| bit1=0 bit0=1 | yes | 0 | 1 |
| bit1=1 bit0=0 | yes | 1 | 0 |
| bit1=1 bit0=1 | yes | 1 | 1 |
| bit1=1 bit0=1 | **no** | 0 | 0 (override ignored) |

Factory: seed its manual-mode flag + command word, invoke its relay updater
(`sub_08018a7c`) — the genuine factory drive code runs (no boot needed, the
override path is self-contained). Ours: `relay_set_override()` + `relay_poll()`
(`src/relay.c`), TDD'd to match the same truth table.

Committed groundwork toward running the firmware fully end-to-end: the M4 model,
the peripheral-ready fakes, the `SpiNorFlash` model (`attach_spi_flash()`),
SysTick injection, and the **`enable_rtos()` exception engine** (above) — which
now context-switches to real PSP tasks. **Next** to run the relay *task* through
the scheduler: resolve the init gate so the firmware actually creates the
control/relay task (supply config-flash contents it validates, and/or the DSP
link) — an init-fidelity problem, no longer an exception-engine one. Once the
task runs, these relay checks could move from a seeded-state call into the common
black-box file.

## The common tests — the SAME code against both images

`tests/test_arm_sim.py` holds only tests that run **identically against either
firmware image**: no symbols, no addresses, no sniffing which firmware is loaded.
The image is passed on the command line as a **flat `.bin`** (a `.hex` is
rejected — convert it first, below), and the Makefile runs the file twice, once
per image, so the two firmwares are compared by each independently satisfying one
shared spec, not by a test that inspects both at once.

```bash
python3 tests/test_arm_sim.py build/firmware.bin     # our firmware
python3 tests/test_arm_sim.py reference/com_flat.bin # the factory oracle (flat .bin)
```

There are two common tests today:

**1. `test_pb7_input_drives_output`** — the black-box pattern: assert a GPIO
contract **without naming any entry point**. It only injects a GPIO input, lets
the firmware's *own event loop* run, and reads a GPIO output — so the test cannot
tell factory from ours apart, which is the point. Contract: hold **PB7** high →
the firmware drives **PB7 high**; hold it low → it does not.

| `set_input("PB7")` | `was_driven("PB7", 1)` |
|---|---|
| 1 | True |
| 0 | False |

In the `ceaa-07xx` image this is factory `sub_0802e452` (debounce-sample PB7 10×,
drive high on a majority); our `pb7_sample_poll()` (`src/gpio_sample.c`, called
from `main`'s loop) mirrors it. The test warms the firmware once, snapshots, and
branches both cases from that copy (above), so *its* loop does the sampling and
driving while the slow boot is paid once. Only observable GPIO is compared, so
the two images can match despite different internals.

**2. `test_boots_and_configures_usart3_gpio`** — boots the image from its reset
vector and asserts `GPIOB->CRH` is configured for USART3 (PB10 = AF-PP `0xB`,
PB11 = floating-in `0x4`). Both firmwares bring the RS485/dongle Modbus link up
the same way, so this doubles as a boot smoke test (the harness runs each image
through its init, not just isolated functions) and a shared-behaviour check.

## Running the tests

```bash
make test-sim                                    # test-sim-ours + test-sim-factory
make test-sim-ours                               # build our fw; common + self-only tests
make factory LXP_FACTORY_HEX=/path/App.hex       # vendor .hex -> reference/com_flat.bin
make test-sim-factory                            # common + factory-only tests on that .bin
make test-sim LXP_FACTORY_HEX=/path/App.hex      # convert + run everything, end to end
```

`make test-sim` runs two sub-targets:

- **`test-sim-ours`** builds our firmware, runs the common file against
  `build/firmware.bin`, then `test_arm_sim_self_only.py`.
- **`test-sim-factory`** runs the common file against the factory `.bin`, then
  `test_arm_sim_factory_only.py` — so the common code is executed against both
  images.

The common runner only accepts a **flat `.bin`**, so a vendor Intel `.hex` is
converted first. `make factory LXP_FACTORY_HEX=/path/App.hex` runs the same
HEX→flat conversion as `tools/hex2bin.py` (gaps filled with `0xFF`, every byte at
its true flash address) and writes `reference/com_flat.bin` (overridable with
`FACTORY_BIN=`). `test-sim-factory` uses `$LXP_FACTORY_BIN` if set, else that
file, and will auto-convert from `$LXP_FACTORY_HEX` if the `.bin` is missing.

Needs `pip install unicorn`. The factory image is never committed (it is
proprietary); `test-sim-factory` **SKIPS** rather than fails when no factory
`.bin` is available, so `make test-sim` is green on our firmware alone.

## Adding a behaviour (the TDD loop)

`pb7_input_drives_output` was built this way, and is the template:

1. Find the contract in the factory image (`tools/disres.py`, `tools/gpio_map.py`):
   which input pin, which output pin, how one drives the other.
2. Write a black-box test: inject the input, `run_reset()` the firmware's loop,
   assert the output. Run it against our firmware — **red**, because our loop
   doesn't do it yet.
3. Implement the behaviour in `src/` and wire it into `main`'s loop (so
   `--gc-sections` keeps it and the *loop* exercises it). Rebuild → **green** on
   ours, and identical to the factory oracle when the image is present.

Keep the asserted surface to *observable GPIO* (and, where needed, Modbus
registers) — never a firmware's internal RAM address — so the factory and our
firmware stay comparable despite different internals. Such black-box tests go in
`test_arm_sim.py`, where the one test runs against both images. Only when a
behaviour genuinely can't be reached as a black box (e.g. it needs a symbol or a
hard-coded address, like the relay tests) does it become target-specific: put
the factory side in `test_arm_sim_factory_only.py`, our side in
`test_arm_sim_self_only.py`, and the shared truth table in `arm_sim_contract.py`
so both are held to one spec. Add more such tests only when there is a second
behaviour to pin; don't pre-build a framework for them.
