# Reverse-engineering tools

Python scripts used to characterize the original `com` binary. All take the
firmware path as an argument and only read it (nothing is executed). Install
deps with `pip install capstone pyelftools`.

> **Run all analysis on the flat image, not the raw `.bin`.** The vendor `.bin`
> is a gap-stripped concatenation of non-contiguous flash regions, so its byte
> offsets are not true flash addresses (see `docs/01`). Convert the `.hex` first:
> `python3 hex2bin.py firmware.hex com_flat.bin` → use `com_flat.bin` everywhere.

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

Example:

```bash
python3 hex2bin.py firmware.hex com_flat.bin
python3 recurse.py com_flat.bin --out ../reference
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
