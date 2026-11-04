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
sim.call("mb_port_init", (cfg_ptr,))   # call a function by symbol name or address
sim.run_reset(max_insn=300_000)        # or boot from the reset vector

sim.get_output("PB7")                  # current driven level (shadow latch)
sim.was_driven("PB7", level=1)         # was it driven (to a level) since clear?
sim.r32(addr) / sim.bit(addr, n)       # peek RAM (status words, flags)
```

## The base case (first proof, against the oracle)

`tests/test_arm_sim.py :: test_factory_pb7_input_drives_output`

In the `ceaa-07xx` image, **`sub_0802e452`** debounce-samples **PB7 as an input**
(10× via `GPIO_ReadInputDataBit`) and, iff the majority read high, drives **PB7
high** via `GPIO_SetBits` and sets status flag `0x2000d890` bit 6. The test flips
the one input and asserts the output (and flag) follow:

| `set_input("PB7")` | `was_driven("PB7", 1)` | flag `0x2000d890` bit6 |
|---|---|---|
| 1 | True | 1 |
| 0 | False | 0 |

That is the minimal input→output causality, proven end-to-end through the real
firmware — the harness working "in the light of day."

## Running our firmware

`tests/test_arm_sim.py :: test_our_firmware_boots_and_configures_usart3_gpio`
boots `build/firmware.bin` from its reset vector and asserts `mb_port_init`
configured `GPIOB->CRH` for USART3 (PB10 = AF-PP `0xB`, PB11 = floating-in
`0x4`). This is the template for future feature tests: drive inputs / call the
subsystem, then assert the GPIO contract — ideally the *same* assertion that
passes against the factory oracle.

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

## Adding a test

1. Find the behaviour in the factory image (`tools/disres.py`, `tools/gpio_map.py`).
2. Write an oracle assertion: seed inputs / call the function, assert the GPIO
   (and any status word) via the API above.
3. Implement the feature in `src/`; point the *same* assertion at `ArmSim.ours()`.
   Until it is implemented, guard the our-firmware side so the suite stays green.
