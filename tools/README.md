# Reverse-engineering tools

Python scripts used to characterize the original `com` binary. All take the
firmware path as an argument and only read it (nothing is executed). Install
deps with `pip install capstone pyelftools`.

> **Run all analysis on the flat image, not the raw `.bin`.** The vendor `.bin`
> is a gap-stripped concatenation of non-contiguous flash regions, so its byte
> offsets are not true flash addresses (see `docs/01`). Convert the `.hex` first:
> `python3 hex2bin.py firmware.hex ceaa-07xx_vE_260214.bin` → use `ceaa-07xx_vE_260214.bin` everywhere.

| Script | Purpose |
|---|---|
| `hex2bin.py` | **Intel HEX → correctly-addressed flat image** (do this first) |
| `analyze.py` | size, entropy map (encryption/compression check), vector table, external IRQ count |
| `disasm.py`  | used-vs-default IRQ handlers, peripheral-address histogram |
| `trace.py`   | disassemble reset handler, PC-relative literal-pool extraction |
| `memmap.py`  | recover reset literals (SystemInit/startup), dump startup, hunt RAM symbols |
| `recurse.py` | recursive-descent function mapper → `symbols.csv`, `callgraph.txt` |
| `strtab.py`  | ordered string catalog + menu enum (`hmi_menu.h`) |
| `xref.py`    | string↔function xrefs, symbol names, Ghidra rename script |
| `emu.py`     | **Unicorn harness**: run firmware functions in a sandbox, capture UART TX, trace calls (`pip install unicorn`) |
| `gpio_map.py` | **GPIO/IO map**: auto-detect the StdPeriph GPIO helpers, resolve every pin's direction/mode + driver (`docs/16`) |
| `periph_map.py` | on-chip peripherals in use (UART/SPI/CAN/TIM/…) by base-address + bit-band scan (`docs/16`) |
| `disres.py` | resolving Thumb disassembler: annotates pc-relative literals + `(base+offset)` RAM targets + call targets (`docs/18`) |
| `arm_sim.py` | **GPIO-instrumented emulator** running our firmware AND the factory image through one API (set_input/get_output/run_reset, snapshot/restore, enable_systick) for behaviour tests (`docs/19`, `tests/test_arm_sim.py`, `make test-sim`) |
| `emu_acfirst.py` | AC-First window→DSP experiment: sweep the RTC, diff RAM to show the windows are evaluated ARM-side, not pushed (`docs/08`) |
| `emu_regrange.py` | drive a Modbus register-group read, dump reg→frame-offset (`docs/08` regs 64-89) |
| `emu_gpio_acfirst.py` | capture GPIO level-drive writes in vs out of the AC-First window → tests the "ARM toggles a relay directly" theory (`docs/14`) |
| `tft.py` | **graphic LCD model**: decodes the bit-banged 4-wire TFT stream (GPIOB PB12–15) unpacking 8 px/byte into the 240×160 monochrome panel image — models the panel both the factory image and our `lcd_tft.c` drive (`docs/28`) |
| `factory_hmi.py` | boot the **factory** image through its RTOS until the display task paints, read the screen, press the real keys to navigate its menus (`docs/28`) |
| `factory_hmi_app.py` | **the factory graphic HMI on screen**, driven by the real image executing in the emulator (`make factory-hmi`, `docs/28`) |
| `dongle_fw.py` | **dongle firmware analyzer** (ESP32-C3 / RISC-V): ESP-IDF image header, segments, app descriptor, RV32 disasm, baud + string xrefs (`docs/26`) |
| `lxp_pcap.py` | **dongle↔cloud capture dissector** (pure stdlib): pcap → Luxpower frames → EG4 device frames; shows which register windows the dongle polls, CRC-checked; `--per-pack` slices the IR 5000 per-battery bank (`docs/34` §2d) |

Dynamic analysis example (validate + call a function):

```bash
python3 emu.py ../reference/ceaa-07xx_vE_260214.bin --selftest          # in-firmware CRC == 0x4B37
python3 emu.py ../reference/ceaa-07xx_vE_260214.bin --call 0x08001482   # run a handler, capture TX
```

Example:

```bash
python3 hex2bin.py firmware.hex ceaa-07xx_vE_260214.bin
python3 recurse.py ceaa-07xx_vE_260214.bin --out ../reference
```

## Recommended next tooling (not yet added)

- **Ghidra** project with the STM32F103 memory map + SVD-derived peripheral
  labels, as the shared RE workspace. A headless Ghidra script can auto-apply
  the recovered string xrefs to name functions.
- **Recursive-descent disassembler** pass (follow calls/branches from Reset)
  to separate code from the font/data tables, instead of the linear sweep the
  current scripts use.
- A **symbol map** (`symbols.csv`: address, name, notes) built up as functions
  are identified, consumed by both Ghidra and the docs.
