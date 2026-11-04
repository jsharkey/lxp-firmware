#!/usr/bin/env python3
"""
arm_sim — a GPIO-instrumented STM32F103 emulator for the EG4 com-MCU firmware.

One harness that runs BOTH:
  * our open-source firmware   (build/firmware.bin + build/firmware.elf symbols)
  * a factory reference image  (reference/com_flat.bin + reference/symbols.csv)

so tests can assert the same observable GPIO behaviour against the factory image
(the oracle) and against our reimplementation as features land.

What it models (enough to test IO behaviour; it is not a full SoC):
  * Cortex-M3 core + flash @0x08000000 + 64 KB RAM @0x20000000 (Unicorn).
  * GPIO ports A-E: writes to BSRR/BRR/ODR update a per-port shadow output
    latch (so get_output(pin) is exact); reads of IDR return whatever
    set_input(pin, level) injected. Every output drive is also recorded.
  * Clock/UART readiness: RCC CR/CFGR reads report HSE/PLL ready and SWS=SW,
    and USART SR reports TXE|TC, so SystemInit and TX loops don't spin forever.
    This lets run_reset() boot our firmware through its init.

Pins are addressed by the names in docs/16-arm-io-map.md ("PB7", "PC8", …);
a few functional aliases from docs/16 & docs/18 are provided for readability.

Read-only w.r.t. the firmware images; executes them in a sandbox. No hardware.
Requires: pip install unicorn   (capstone only if you also disassemble).
"""
import os, struct, csv, subprocess
from unicorn import *
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_PC)

FLASH_BASE = 0x08000000
RAM_BASE   = 0x20000000
RAM_SIZE   = 0x10000          # 64 KB (STM32F103VE)
PERIPH     = 0x40000000
PERIPH_SZ  = 0x00030000
CORE       = 0xE0000000
CORE_SZ    = 0x00100000
STOP       = 0x56000000       # LR sentinel: landing here ends a call()
STACK_TOP  = RAM_BASE + RAM_SIZE - 0x400

GPIO = {"A":0x40010800,"B":0x40010c00,"C":0x40011000,"D":0x40011400,"E":0x40011800}
R_CRL,R_CRH,R_IDR,R_ODR,R_BSRR,R_BRR = 0x00,0x04,0x08,0x0c,0x10,0x14
RCC = 0x40021000
USARTS = {0x40013800,0x40004400,0x40004800,0x40004c00,0x40005000}
USART_SR_READY = 0x000000C0   # TXE|TC

# functional aliases (best-effort names from docs/16 & docs/18)
ALIASES = {
    "KEY1":"PA8","KEY2":"PA11","KEY3":"PC8","KEY4":"PC9",
    "RELAY_TRANSFER_A":"PA12","RELAY_TRANSFER_B":"PB3",
    "RELAY_RUN_ENABLE":"PB2","RELAY_BYPASS":"PC6",
    "RELAY_SLOW":"PC5","RELAY_EPS_DRY":"PD11",
    "BITBANG_DATA":"PB7",   # the docs/16 PB6/PB7 bit-banged line
}

def parse_pin(name):
    """'PB7' or an alias -> ('B', 7)."""
    name = ALIASES.get(name, name)
    if len(name) >= 3 and name[0] == "P" and name[1] in GPIO and name[2:].isdigit():
        return name[1], int(name[2:])
    raise ValueError("unknown pin %r" % name)

def load_symbols_csv(path):
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out[r["name"]] = int(r["addr"], 16)
    return out

def load_symbols_nm(elf_path, nm="arm-none-eabi-nm"):
    out = {}
    for ln in subprocess.check_output([nm, elf_path], text=True).splitlines():
        p = ln.split()
        if len(p) == 3 and p[1] in "tTwW":          # thumb code symbols
            try: out[p[2]] = int(p[0], 16)
            except ValueError: pass
    return out

def is_intel_hex(path):
    """True if the file looks like Intel HEX (ASCII, first record starts ':')."""
    with open(path, "rb") as f:
        return f.read(64).lstrip()[:1] == b":"

def hex_to_flat(hex_path, base=FLASH_BASE, fill=0xFF):
    """Intel HEX -> correctly-addressed flat image bytes (same as tools/hex2bin.py,
    so a vendor .hex can be loaded directly without a separate convert step).
    Read as bytes (latin-1) so a mis-pointed binary fails with a clear error,
    not a UnicodeDecodeError."""
    mem, linbase = {}, 0
    with open(hex_path, "rb") as f:
        for raw in f.read().split(b"\n"):
            ln = raw.strip()
            if not ln.startswith(b":"):
                continue
            b = bytes.fromhex(ln[1:].decode("latin-1"))
            n, addr, typ, data = b[0], (b[1] << 8) | b[2], b[3], b[4:4+b[0]]
            if (sum(b) & 0xFF) != 0:
                raise ValueError("bad checksum: %s" % ln[:32])
            if typ == 0x00:
                for i, by in enumerate(data):
                    mem[linbase + addr + i] = by
            elif typ == 0x04:
                linbase = ((data[0] << 8) | data[1]) << 16
            elif typ == 0x02:
                linbase = ((data[0] << 8) | data[1]) << 4
            elif typ == 0x01:
                break
    if not mem:
        raise ValueError("%s is not an Intel HEX file (no ':' records found)" % hex_path)
    hi = max(mem)
    flat = bytearray([fill]) * (hi - base + 1)
    for a, by in mem.items():
        flat[a - base] = by
    return bytes(flat)

def load_flat(path):
    """Load a factory image from either an Intel HEX or a raw flat binary,
    auto-detected by content. Returns flat image bytes."""
    return hex_to_flat(path) if is_intel_hex(path) else open(path, "rb").read()


class ArmSim:
    def __init__(self, image, symbols=None):
        # image: a path to a flat .bin, or the flat image bytes directly
        self.data = bytes(image) if isinstance(image, (bytes, bytearray)) \
            else open(image, "rb").read()
        self.names = dict(symbols or {})
        self.shadow = {p: 0 for p in GPIO}     # per-port output latch (ODR shadow)
        self.drive_log = []                     # [(port, pin, 'HIGH'|'LOW')]
        self._build()

    # ---- construction helpers -------------------------------------------
    @classmethod
    def factory(cls, image="reference/com_flat.bin", symbols="reference/symbols.csv"):
        return cls(image, load_symbols_csv(symbols))

    @classmethod
    def from_hex(cls, hex_path, symbols=None):
        """Load a vendor Intel-HEX image directly (converted to flat in-memory)."""
        sym = load_symbols_csv(symbols) if isinstance(symbols, str) else symbols
        return cls(hex_to_flat(hex_path), sym)

    @classmethod
    def from_image(cls, path, symbols=None):
        """Load a factory image, auto-detecting Intel HEX vs raw flat binary."""
        sym = load_symbols_csv(symbols) if isinstance(symbols, str) else symbols
        return cls(load_flat(path), sym)

    @classmethod
    def ours(cls, image="build/firmware.bin", elf="build/firmware.elf"):
        return cls(image, load_symbols_nm(elf))

    def _build(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        try: uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
        except Exception: pass
        fsz = (len(self.data) + 0xFFF) & ~0xFFF
        uc.mem_map(FLASH_BASE, max(fsz, 0x80000))
        uc.mem_write(FLASH_BASE, self.data)
        uc.mem_map(RAM_BASE, RAM_SIZE)
        uc.mem_map(PERIPH, PERIPH_SZ)
        uc.mem_map(CORE, CORE_SZ)
        uc.mem_map(STOP, 0x1000)                       # zero-filled -> nop sled
        for b in USARTS: uc.mem_write(b, struct.pack("<I", USART_SR_READY))
        uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write, begin=PERIPH, end=PERIPH+PERIPH_SZ)
        uc.hook_add(UC_HOOK_MEM_READ,  self._on_read,  begin=PERIPH, end=PERIPH+PERIPH_SZ)
        uc.hook_add(UC_HOOK_CODE, self._on_code)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.uc = uc

    # ---- peripheral behaviour -------------------------------------------
    def _on_write(self, uc, access, addr, size, value, ud):
        base = addr & 0xFFFFFC00
        off  = addr - base
        if base in GPIO.values():
            port = [k for k, v in GPIO.items() if v == base][0]
            v16 = value & 0xFFFF
            if off == R_BSRR:
                self._drive(port, v16 & 0xFFFF, (value >> 16) & 0xFFFF)
            elif off == R_BRR:
                self._drive(port, 0, v16)
            elif off == R_ODR:
                cur = self.shadow[port]
                self._drive(port, v16 & ~cur, (~v16) & cur & 0xFFFF)
                self.shadow[port] = v16
        return True

    def _drive(self, port, set_mask, reset_mask):
        for i in range(16):
            if (set_mask >> i) & 1:
                self.shadow[port] |= (1 << i); self.drive_log.append((port, i, "HIGH"))
            if (reset_mask >> i) & 1:
                self.shadow[port] &= ~(1 << i); self.drive_log.append((port, i, "LOW"))
        # keep the mapped ODR consistent for code that reads it back
        self.uc.mem_write(GPIO[port] + R_ODR, struct.pack("<I", self.shadow[port]))

    def _on_read(self, uc, access, addr, size, value, ud):
        base = addr & 0xFFFFFF00
        off  = addr & 0xFF
        if base == RCC and off == 0x00:                      # RCC_CR: force HSE/PLL/HSI ready
            cur = struct.unpack("<I", uc.mem_read(RCC, 4))[0]
            uc.mem_write(RCC, struct.pack("<I", cur | (1<<1) | (1<<17) | (1<<25)))
        elif base == RCC and off == 0x04:                    # RCC_CFGR: SWS mirrors SW
            cur = struct.unpack("<I", uc.mem_read(RCC+4, 4))[0]
            uc.mem_write(RCC+4, struct.pack("<I", (cur & ~(3<<2)) | ((cur & 3) << 2)))
        elif (addr & ~0xFF) in USARTS and off == 0x00:       # USART_SR: keep TXE|TC
            uc.mem_write(addr & ~0xFF, struct.pack("<I", USART_SR_READY))
        return True

    def _on_code(self, uc, addr, size, ud):
        if addr == STOP:
            uc.emu_stop()

    def _on_unmapped(self, uc, access, addr, size, value, ud):
        try: uc.mem_map(addr & ~0xFFF, 0x1000); return True
        except Exception: return False

    # ---- public GPIO API -------------------------------------------------
    def set_input(self, pin, level):
        """Inject an external level on an input pin (sets its IDR bit)."""
        port, bit = parse_pin(pin)
        idr = struct.unpack("<I", self.uc.mem_read(GPIO[port] + R_IDR, 4))[0]
        idr = (idr | (1 << bit)) if level else (idr & ~(1 << bit))
        self.uc.mem_write(GPIO[port] + R_IDR, struct.pack("<I", idr & 0xFFFF))

    def get_output(self, pin):
        """Current driven level of an output pin (from the shadow latch)."""
        port, bit = parse_pin(pin)
        return (self.shadow[port] >> bit) & 1

    def was_driven(self, pin, level=None):
        """True if the pin was driven since the last clear (optionally to level)."""
        port, bit = parse_pin(pin)
        want = None if level is None else ("HIGH" if level else "LOW")
        return any(p == port and i == bit and (want is None or d == want)
                   for (p, i, d) in self.drive_log)

    def clear_drives(self):
        self.drive_log = []

    # ---- symbols / memory / execution -----------------------------------
    def sym(self, name):
        if name in self.names: return self.names[name]
        raise KeyError("no symbol %r" % name)

    def w32(self, a, v): self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
    def r32(self, a): return struct.unpack("<I", self.uc.mem_read(a, 4))[0]
    def wbytes(self, a, b): self.uc.mem_write(a, bytes(b))
    def rbytes(self, a, n): return bytes(self.uc.mem_read(a, n))
    def bit(self, addr, n): return (self.r32(addr) >> n) & 1

    def call(self, func, args=(), count=2_000_000):
        """Call a firmware function by name or address; returns r0."""
        addr = self.sym(func) if isinstance(func, str) else func
        uc = self.uc
        for i, v in enumerate(args[:4]):
            uc.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3][i],
                         v & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        try:
            uc.emu_start((addr & ~1) | 1, STOP, count=count)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            if (pc & ~1) != STOP:
                raise RuntimeError("emu fault %s at pc=0x%08x" % (e, pc))
        return uc.reg_read(UC_ARM_REG_R0)

    def vector_base(self):
        """Locate the Cortex-M vector table (initial SP in RAM, reset PC in
        flash). Handles our monolithic image (@0x08000000) and the factory App
        that sits above an absent bootloader (@0x08005000) — so callers never
        need to hard-code where a given image boots."""
        n = len(self.data)
        for off in range(0, min(n, 0x80000) - 8, 0x100):
            sp = struct.unpack_from("<I", self.data, off)[0]
            pc = struct.unpack_from("<I", self.data, off + 4)[0]
            if (RAM_BASE <= sp <= RAM_BASE + RAM_SIZE
                    and (pc & 1) and FLASH_BASE <= (pc & ~1) < FLASH_BASE + n):
                return FLASH_BASE + off
        raise RuntimeError("no vector table found in image")

    def run_reset(self, max_insn=500_000, vector_base=None):
        """Boot from the image's own reset vector and run its event loop for up
        to max_insn instructions (black box: no entry address needed). A bounded
        boot stops wherever it is in the loop; callers assert on observed IO."""
        base = self.vector_base() if vector_base is None else vector_base
        sp = self.r32(base); pc = self.r32(base + 4)
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        try:
            self.uc.emu_start(pc & ~1 | 1, 0xFFFFFFFF, count=max_insn)
        except UcError:
            pass
        return self

    def run_until_output(self, out_pin, level=1, settle_input=None,
                         settle_reads=40, max_insn=8_000_000, vector_base=None):
        """Boot the firmware and run its own event loop until it drives `out_pin`
        to `level` -- then stop immediately. This keeps the black box (no entry
        point named) but finishes as soon as the expected edge happens instead of
        burning the whole instruction budget.

        For the negative case (the edge should NOT happen): pass `settle_input`,
        and the run also stops once that input pin has been sampled (its IDR read)
        `settle_reads` times without the edge -- i.e. the loop looked at the input
        enough times and chose not to drive. Returns True iff `out_pin` was driven
        to `level`. `max_insn` is only a safety cap."""
        op, ob = parse_pin(out_pin)
        hooks = []
        def _stop_on_drive(uc, access, addr, size, value, ud):
            off = addr - GPIO[op]
            drove = None
            if off == R_BSRR:
                if (value >> ob) & 1: drove = 1
                elif (value >> (16 + ob)) & 1: drove = 0
            elif off == R_BRR and (value >> ob) & 1:
                drove = 0
            elif off == R_ODR:
                drove = (value >> ob) & 1
            if drove == level:
                uc.emu_stop()
            return True
        hooks.append(self.uc.hook_add(UC_HOOK_MEM_WRITE, _stop_on_drive,
                                      begin=GPIO[op], end=GPIO[op] + 0x18))
        if settle_input is not None:
            ip, _ = parse_pin(settle_input)
            idr = GPIO[ip] + R_IDR
            n = [0]
            def _stop_on_settle(uc, access, addr, size, value, ud):
                n[0] += 1
                if n[0] >= settle_reads:
                    uc.emu_stop()
            hooks.append(self.uc.hook_add(UC_HOOK_MEM_READ, _stop_on_settle,
                                          begin=idr, end=idr + 4))
        try:
            self.run_reset(max_insn=max_insn, vector_base=vector_base)
        finally:
            for h in hooks:
                self.uc.hook_del(h)
        return self.was_driven(out_pin, level=level)
