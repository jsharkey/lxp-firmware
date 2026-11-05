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
sim.attach_spi_flash("PA4")            # RAM-backed SPI NOR on SPI1 (blank chip)
sim.attach_config_flash("PA4")         # ...pre-provisioned with valid config so
                                       # boot clears config bring-up (see below)

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

**A Cortex-M exception engine (`enable_rtos()`).** Unicorn emulates the CPU but
not the exception machinery the switch relies on, so `enable_rtos()` models it:
exception **entry** hardware-stacks `{r0-r3,r12,lr,pc,xpsr}` on the active stack
and vectors to the handler; **EXC_RETURN** (Unicorn raises `UC_HOOK_INTR` when
execution branches to `0xFFFFFFFx`) unstacks and resumes the task; **SysTick** is
injected between run quanta and **PendSV** is taken whenever thread code is
pending one with interrupts enabled. The firmware's own SysTick/PendSV handlers
then do the real scheduling and the FreeRTOS-style switch (`mrs/msr psp` +
`{r4-r11}`).

*Two fixes made the switch actually correct* (before them it ran one switch then
faulted on a zeroed frame):

- **Deferred SysTick.** A tick that comes due while interrupts are masked (the
  firmware spends much of its time in short critical sections) is held pending,
  not dropped — so ticks keep advancing instead of being lost whenever a run
  quantum ends inside a `cpsid`/`cpsie` region.
- **Stack banking without `CONTROL.SPSEL`.** Unicorn does not reliably keep
  `CONTROL.SPSEL` across our manual EXC_RETURN, so a handler's `mrs psp` read a
  stale value and the second switch corrupted. The engine now keeps one active
  `SP` and swaps it between the task stack and a shadow MSP itself, keeping the
  `PSP` register current for the firmware's `mrs/msr psp`. With this the engine
  **context-switches cleanly thousands of times** on the factory image (no halt).

**The config-flash gate — found, and resolved.** Earlier it looked like the
relay task was "never created"; the real cause was that **boot never finishes
config bring-up on a blank chip**, so it never reaches task creation at all.
Tracing it out (stuck call chain `sub_0802e4dc` → `sub_0801_4696` →
`sub_0801_683c`, the config loader):

- The settings live in a **journaled store on the SPI config flash**: six 8 KB
  regions, slot *N* at `N*0x2000`, each a ring of 256-byte records. A record is
  **250 payload bytes + a 16-bit Modbus CRC** of that payload at `[0xFA:0xFC]`
  (little-endian) + a **`0xA5` marker** at `[0xFF]`. The loader scans a region
  newest-first and takes the first record whose marker and CRC check out (CRC
  `sub_0801_60bc` is byte-for-byte the repo's Modbus CRC-16). If a slot has no
  valid record it falls back to a **compiled-in default** in the MCU's own flash
  (`0x0807F800` for slot 0, `0x0807F900` for slot 5).
- A blank SPI chip has no records, and in the ceaa-07xx dump those default pages
  are **past the end of the image** (it ends exactly at `0x0807F800`), so both
  sources are empty and boot loops re-scanning — *slow*, not hung: each scan is
  32 bit-banged SPI page reads, so all six slots × retries take ~15 M instructions.

**`sim.attach_config_flash()` clears it.** It attaches an SPI NOR pre-provisioned
with one valid record (`make_config_record()`, which frames a payload with the
right CRC + marker) at the top page of each slot — the way a factory-programmed
board presents config. The loader then validates all six slots on the first read
(config reads drop ~1150 → 12), and boot runs **all the way through task
registration**: `sub_0802e2f0` registers the periodic tasks via `sub_0802e578`
(= `pxPortInitialiseStack`, so each is a real preemptive task with its own
stack), **including the relay/control loop `sub_0801b3dc` as task id 1** (300-word
stack). It then starts the scheduler (`sub_0801c466` = `vPortStartFirstTask`:
set PendSV pri, `PSP=0`, `PENDSVSET`, `cpsie i; b .`) and `enable_rtos()`
context-switches into the first task, then runs the scheduler — thousands of
clean PendSV switches that dispatch the registered tasks, including the
relay/control task `sub_0801b3dc`.

**How the scheduler picks a task** (reverse-engineered). The periodic driver
`sub_0802f50c` runs each SysTick: per task it counts to the task's period and
then `sub_0801_4af0(id,1)` sets that task's bit in a ready bitmask
(`0x2000da16`). A task blocks by clearing *its own* bit and yielding
(`sub_0801_c544` → selector `sub_0801_c4f4`, which returns the lowest set bit via
the lookup table at `0x20002204`, then PENDSVSET). The idle task is id 0 — the
lowest bit, i.e. highest priority — and is itself periodic, so it is re-marked
ready and reselected constantly.

**Why the ready bits were being cleared before selection — and the fix.** The
tick marks the relay task (id 1) ready and the mask reaches e.g. `0x01c3` (ids
0,1,6,7,8), yet selection kept reading the mask as `0` and falling through to the
idle task. The cause was **PendSV taken too late**. A yield runs
`selector → cur_id := <picked id> → PENDSVSET` inside a critical section and
expects PendSV to switch the instant interrupts re-enable. The engine instead
deferred it to the next run quantum, so the *still-running* idle task looped back
into its wait and — now reading the just-updated `cur_id` — cleared **the newly
selected task's** ready bit (`actual_running=0, cur_id=1 → clears bit 1`), and
repeated down the mask until it was empty; the late PendSV then found only the
idle task ready. The fix makes PendSV **prompt**: a per-block hook stops
emulation at the next block boundary (a safe instruction boundary — stopping a
store hook mid-write just re-executes it) as soon as a pending exception can be
taken, so the switch happens at the yield's crit-exit, before idle runs on.

With that, the scheduler **dispatches the real tasks**: id 1, 2, 5, 6, 7, 8, 9 all
get switched in, and the relay/control task `sub_0801b3dc` runs under the
scheduler and **drives the power-path relays** (TRANSFER_A/B, RUN_EN, SLOW,
BYPASS) on its own — boot → config → scheduler → relay task, end to end, from
`attach_config_flash()` + `enable_rtos()` alone.

**What's left.** One periodic task does a bounded "start op, wait ready" poll on
a peripheral at `0x40006400` that the harness doesn't model, so it spins to its
timeout with interrupts off (the scheduler still makes progress — that task just
wastes its slice; faking the ready bit at `0x40006404` roughly halves the run
cost). Modelling that (and any siblings) is a loose end, not a blocker. **The
relay parity tests below don't depend on any of this** — they run the factory's
real relay code directly with seeded state.

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

Both take their image on the command line, the same style as `test_arm_sim.py`
(no path-guessing, no environment variables). The factory file needs only the
flat `.bin`; the self file also needs the `.elf`, since it calls our firmware's
functions *by name* and so needs the symbol table:

```bash
python3 tests/test_arm_sim_self_only.py    build/firmware.bin build/firmware.elf
python3 tests/test_arm_sim_factory_only.py reference/com_flat.bin
```

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

The firmware now runs fully end-to-end in the harness: the M4 model, the
peripheral-ready fakes, the `SpiNorFlash` model (`attach_spi_flash()`), the
config-flash provisioning (`attach_config_flash()`, which clears the boot config
gate), SysTick injection, and the **`enable_rtos()` exception engine** (above)
together take the factory image from reset through config, into its preemptive
scheduler, which **dispatches the relay/control task `sub_0801b3dc` — and it
drives the power-path relays on its own**. So these relay checks *could* now move
from a seeded-state direct call into a scheduler-driven black-box form; they are
kept as direct calls for speed and determinism (the full run is millions of
instructions), and because that form also validates our firmware, which has no
such scheduler.

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

There are four common tests today:

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

**3. `test_modbus_charge_current_write_read`** — wire-level **dongle Modbus**
over USART3 (docs/04): set holding register 101 (`HR_CHARGE_CURR`) to 42 with a
`0x06` write-single, read it back with a `0x03` read-holding, then overwrite it
with 43 and confirm the edit. It drives the image purely as a Modbus slave — it
frames a request, feeds the bytes in on the UART, lets the firmware's own loop
answer, and parses the reply — naming no symbol, so the one test applies to any
image that speaks the EG4 dongle protocol (`addr func SN[10] body CRC`,
little-endian, CRC-16/MODBUS; see `include/inv/modbus.h`). The UART plumbing is
`tests/arm_sim_modbus.py` (`ModbusDongle`), which hooks the USART3 data/status
registers through the sim's `uc` handle (no `tools/arm_sim.py` change) and runs
with SysTick on so the RTU inter-frame timer advances. USART3 currently also
carries the DSP config push (a placeholder collision — `src/dsp/dsp_link_port.c`),
so it stops on the first contiguous, CRC-valid response frame matching the
request rather than on a byte count.

> **Expected-red for now.** This passes against our firmware (whose Modbus RX is
> polled in `mb_port_poll`) but **fails against the factory image**, which parses
> RX in the USART3 interrupt that the harness does not yet fire — and both
> firmwares' dongle paths are still being built out. That is fine: the test
> pins the target contract. A red common test fails `make test-sim`, which runs
> every block regardless and reports the failure at the end (see *Running the
> tests*), so the other blocks still show.

**4. `test_can_battery_soc_soh_reaches_modbus`** — end-to-end **battery BMS CAN →
Modbus** (docs/20). The pack reports SOC/SOH on CAN1 ID `0x355`; the ARM polls
CAN1, caches the pack state, and serves it as Modbus **input register 5**
(`IR_SOC_SOH`: low byte SOC %, high byte SOH %). The test injects a `0x355` frame
on the battery bus and then reads IR 5 over the dongle, asserting the values
crossed from CAN to Modbus. The CAN plumbing is `tests/arm_sim_can.py`
(`CanBattery`), which models just enough of the bxCAN receive FIFO 0 at
`0x40006400` (the registers a polled reader touches) through the sim's `uc`
handle — no `tools/arm_sim.py` change — matching the recovered fact that the
com-MCU polls CAN1 with no IRQ (docs/20).

> **Green on ours; still red on the factory.** Our firmware now implements this
> end to end: `can_port_init`/`can_port_poll` (`src/can/can_port.c`) drain CAN1
> FIFO 0 each loop, `bms_can_on_frame` (`src/can/bms_can.c`) decodes `0x355`, and
> `main` publishes it to `IR_SOC_SOH` — so the test passes against
> `build/firmware.bin`. It **fails against the factory image**, which polls CAN1
> from an RTOS task the harness does not schedule (so it sends no reply). The
> decoder also has a host unit test (`tests/test_bms_can.c`, under `make test`).

## Running the tests

```bash
make test-sim                                    # test-sim-ours + test-sim-factory
make test-sim-ours                               # build our fw; common + self-only tests
make factory LXP_FACTORY_HEX=/path/App.hex       # vendor .hex -> reference/com_flat.bin
make test-sim-factory                            # common + factory-only tests on that .bin
make test-sim LXP_FACTORY_HEX=/path/App.hex      # convert + run everything, end to end
```

`make test-sim` runs two halves:

- **`test-sim-ours`** builds our firmware, runs the common file against
  `build/firmware.bin`, then `test_arm_sim_self_only.py`.
- **`test-sim-factory`** runs the common file against the factory `.bin`, then
  `test_arm_sim_factory_only.py` — so the common code is executed against both
  images.

Every block runs even if an earlier one fails; `make test-sim` reports the
failure only at the end (exit non-zero). This keeps the whole green/red picture
visible when an expected-red test (e.g. the dongle/CAN scaffolding) is present,
rather than stopping at the first failure. Each block's banner header is the
delimiter.

The common runner only accepts a **flat `.bin`**, so a vendor Intel `.hex` is
converted first. The factory `.bin` (`reference/com_flat.bin`, overridable with
`FACTORY_BIN=`, which also honours `$LXP_FACTORY_BIN`) is an ordinary make target:
its rule runs the same HEX→flat conversion as `tools/hex2bin.py` (gaps filled with
`0xFF`, every byte at its true flash address) from `$LXP_FACTORY_HEX`, built only
if the `.bin` is missing. `make factory` is the friendly alias, and because
`test-sim-factory` simply *depends* on that `.bin`, it is converted on demand —
`make test-sim-factory` and `make test-sim LXP_FACTORY_HEX=…` just work.

Needs `pip install unicorn`. The factory image is never committed (it is
proprietary). `make test-sim` runs the factory half only when an image is
available (a `.hex` to convert, or a `.bin` already on disk), so it stays green on
our firmware alone; run `test-sim-factory` directly without one and it tells you
to set `LXP_FACTORY_HEX`.

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
