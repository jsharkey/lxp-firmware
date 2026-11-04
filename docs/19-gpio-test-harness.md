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

## Parity behaviours (factory oracle == our firmware)

The core pattern is a **parity test**: one GPIO contract, asserted against both
the factory image (the oracle) and our firmware, so our reimplementation is
held to the shipped behaviour. Contracts live in the `BEHAVIOURS` list in
`tests/test_arm_sim.py`; two tests consume it:

- `test_behaviours_ours` — our firmware satisfies each contract (runs always).
- `test_behaviours_factory_vs_ours_parity` — factory and ours drive the output
  **identically** (SKIPs when no factory image is present).

The first contract, **`pb7_input_drives_output`** (the base case): in the
`ceaa-07xx` image, **`sub_0802e452`** debounce-samples **PB7 as an input** (10×)
and, iff the majority read high, drives **PB7 high** via `GPIO_SetBits`. Our
`pb7_sample_poll()` (`src/gpio_sample.c`) reproduces it. The observable contract
is the GPIO drive (internal status flags are not part of parity):

| `set_input("PB7")` | `was_driven("PB7", 1)` — factory | — ours |
|---|---|---|
| 1 | True | True |
| 0 | False | False |

Minimal input→output causality, proven end-to-end through **both** firmwares.

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

1. Find it in the factory image (`tools/disres.py`, `tools/gpio_map.py`): which
   input pin, which output pin, and the input→output contract.
2. Append a `dict(...)` to `BEHAVIOURS` in `tests/test_arm_sim.py` — `in_pin`,
   `out_pin`, `factory` (address/symbol), `ours` (the symbol you will write),
   and `expected`. Run `make test-sim`: the parity/ours tests go **red** (no
   such symbol yet), the factory side already matches.
3. Implement the function in `src/` and wire it in (reference it from `main`
   so `--gc-sections` keeps it). Rebuild; `make test-sim` goes **green** on both.

This is exactly how `pb7_input_drives_output` + `pb7_sample_poll()` were added.
Behaviours whose output depends on more than one input, or on a status word,
extend `_observe()` similarly — keep the asserted surface to *observable GPIO*
so factory and our firmware can be compared even with different internals.
