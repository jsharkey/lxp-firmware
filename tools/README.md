# Reverse-engineering tools

Python scripts used to characterize the original `com` binary. All take the
firmware path as an argument and only read it (nothing is executed). Install
deps with `pip install capstone pyelftools`.

| Script | Purpose |
|---|---|
| `analyze.py` | size, entropy map (encryption/compression check), vector table, external IRQ count |
| `disasm.py`  | used-vs-default IRQ handlers, peripheral-address histogram |
| `trace.py`   | disassemble reset handler, PC-relative literal-pool extraction |
| `memmap.py`  | recover reset literals (SystemInit/startup), dump startup, hunt RAM symbols |

Example:

```bash
python3 analyze.py /path/to/com_firmware.bin
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
