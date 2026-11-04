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
# boot the image's own loop (black box) and stop at the expected edge; for the
# no-edge case, stop once the input has been sampled settle_reads times:
driven = sim.run_until_output("PB7", level=1, settle_input="PB7", settle_reads=40)
sim.run_reset(max_insn=300_000)        # or run a fixed budget
sim.call("mb_port_init", (cfg_ptr,))   # or call one function, by symbol/address

sim.get_output("PB7")                  # current driven level (shadow latch)
sim.was_driven("PB7", level=1)         # was it driven (to a level) since clear?
sim.r32(addr) / sim.bit(addr, n)       # peek RAM (status words, flags)
```

`run_reset()` finds the vector table itself (`vector_base()`), so our
monolithic image (@`0x08000000`) and the factory App that sits above an absent
bootloader (@`0x08005000`) both "just boot".

## The parity test (factory oracle == our firmware), black box

`tests/test_arm_sim.py :: test_pb7_input_drives_output` is the pattern: assert a
GPIO contract against both firmwares **without naming any entry point**. It only
injects a GPIO input, lets each firmware's *own event loop* run, and reads a GPIO
output — so the test cannot tell factory from ours apart, which is the point.

The contract: hold **PB7** high → the firmware drives **PB7 high**; hold it low →
it does not.

| `set_input("PB7")` | `was_driven("PB7", 1)` — factory | — ours |
|---|---|---|
| 1 | True | True |
| 0 | False | False |

In the `ceaa-07xx` image this is factory `sub_0802e452` (debounce-sample PB7 10×,
drive high on a majority); our `pb7_sample_poll()` (`src/gpio_sample.c`, called
from `main`'s loop) mirrors it. The test runs each firmware from its reset
vector, so *their* loops do the sampling and driving, and `run_until_output()`
stops the instant the expected edge appears (or, for the low case, once PB7 has
been sampled enough times) — so the suite finishes in a fraction of a second
without a factory image, rather than burning a multi-million-instruction budget.
It asserts our firmware propagates PB7, and — when a factory image is available —
that the two behave identically; with no factory image the our-firmware check
still runs. Only the observable GPIO is compared, so the two can match despite
different internals.

## Running our firmware (boot smoke test)

`test_our_firmware_boots_and_configures_usart3_gpio` boots `build/firmware.bin`
from its reset vector and asserts `mb_port_init` configured `GPIOB->CRH` for
USART3 (PB10 = AF-PP `0xB`, PB11 = floating-in `0x4`) — proof the harness runs
our firmware through its init, not just isolated functions.

## Running the tests

```bash
make test-sim                                   # builds our fw, runs the harness tests
LXP_FACTORY_HEX=/path/App.hex    make test-sim   # vendor .hex (converted in-memory)
LXP_FACTORY_BIN=/path/com_flat.bin make test-sim # or a pre-converted flat image
```

Needs `pip install unicorn`. The factory image is never committed (it is
proprietary); tests that need it **SKIP** rather than fail when it is absent, so
`make test-sim` is green on our firmware alone. Point `LXP_FACTORY_HEX` (or
`LXP_FACTORY_BIN`) at the factory image to run the oracle checks — **the format
is auto-detected by content**, so either var accepts either an Intel `.hex` (the
harness runs the same HEX→flat conversion as `tools/hex2bin.py`, in memory) or an
already-converted flat `.bin`. `LXP_FACTORY_HEX` takes precedence if both are set.

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
firmware stay comparable despite different internals. Add more such tests only
when there is a second behaviour to pin; don't pre-build a framework for them.
