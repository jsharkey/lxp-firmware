#!/usr/bin/env python3
"""
Unicorn emulation harness for the ARM 'com' firmware (STM32F103, Cortex-M3).

Runs the *correctly-addressed* flat image (tools/hex2bin.py) in Unicorn so we can
call individual firmware functions and watch what they do — in particular, which
UART they transmit on and with what bytes. This is how we resolve the
"does an HMI/Modbus setting change go OUT to the DSP" direction question without
hardware (see docs/05-dsp-link.md).

Peripherals are stubbed: register space is plain RAM pre-seeded so UART TX/flag
polls don't hang; every write to a USART data register (base+0x04) is captured
and tagged by which UART it was. Core peripherals (SysTick/SCB/NVIC) are mapped
so init code doesn't fault.

This only *reads* the firmware image and executes it in a sandbox; it touches no
hardware. Requires: pip install unicorn capstone.
"""
import sys, struct, csv, argparse
from unicorn import *
from unicorn.arm_const import *

FLASH_BASE = 0x08000000
RAM_BASE   = 0x20000000
RAM_SIZE   = 0x10000            # 64 KB
PERIPH     = 0x40000000
PERIPH_SZ  = 0x00030000
CORE       = 0xE0000000
CORE_SZ    = 0x00100000
STOP       = 0x56000000         # return sentinel pad
STACK_TOP  = RAM_BASE + RAM_SIZE - 0x400

USARTS = {0x40013800:"USART1", 0x40004400:"USART2", 0x40004800:"USART3",
          0x40004c00:"UART4",  0x40005000:"UART5"}
USART_SR_READY = 0x00C0         # TXE|TC set so TX loops proceed

class Emu:
    def __init__(self, image_path, symbols_path=None, trace_calls=False):
        self.data = open(image_path, "rb").read()
        self.names = {}
        if symbols_path:
            try:
                for r in csv.DictReader(open(symbols_path)):
                    self.names[int(r["addr"], 16)] = r["name"]
            except FileNotFoundError:
                pass
        self.tx = []            # (uart_name, byte)
        self.mem_writes = []    # (pc, addr, size, value)
        self.calls = []         # (pc, target, name)
        self.trace_calls = trace_calls
        self.ftrace = []        # ordered list of named functions entered
        self.trace_funcs = False
        self._entries = set(self.names)
        self._last_f = None
        self.watch = None       # (lo, hi) RAM range to log writes for
        self.stubs = {}         # addr -> return value: force an immediate return
        self._build()

    def _build(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        try: uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
        except Exception: pass
        # flash (round up to page)
        fsz = (len(self.data) + 0xFFF) & ~0xFFF
        uc.mem_map(FLASH_BASE, max(fsz, 0x80000))
        uc.mem_write(FLASH_BASE, self.data)
        uc.mem_map(RAM_BASE, RAM_SIZE)
        uc.mem_map(PERIPH, PERIPH_SZ)
        uc.mem_map(CORE, CORE_SZ)
        uc.mem_map(STOP, 0x1000)       # zero-filled = "movs r0,r0" nops
        # pre-seed every USART status register = ready
        for base in USARTS:
            uc.mem_write(base, struct.pack("<I", USART_SR_READY))
        uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write, begin=PERIPH, end=PERIPH+PERIPH_SZ)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._on_ram_write, begin=RAM_BASE, end=RAM_BASE+RAM_SIZE)
        uc.hook_add(UC_HOOK_CODE, self._on_code)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.uc = uc

    # keep USART status "ready" after firmware clears it; capture DR writes
    def _on_write(self, uc, access, address, size, value, ud):
        base = address & ~0xFF
        off  = address & 0xFF
        if base in USARTS and off == 0x04:          # USART_DR (transmit)
            self.tx.append((USARTS[base], value & 0xFF))
        if base in USARTS and off == 0x00:          # firmware wrote SR: re-assert ready next read
            pass
        return True

    def _on_code(self, uc, address, size, ud):
        if address == STOP:
            uc.emu_stop(); return
        if address in self.stubs:                 # force immediate return
            uc.reg_write(UC_ARM_REG_R0, self.stubs[address] & 0xFFFFFFFF)
            lr = uc.reg_read(UC_ARM_REG_LR)
            uc.reg_write(UC_ARM_REG_PC, lr)
            return
        if self.trace_funcs and address in self._entries and address != self._last_f:
            self._last_f = address
            if len(self.ftrace) < 4000:
                self.ftrace.append(address)

    def _on_ram_write(self, uc, access, address, size, value, ud):
        if self.watch and self.watch[0] <= address < self.watch[1]:
            pc = uc.reg_read(UC_ARM_REG_PC)
            self.mem_writes.append((pc, address, size, value))
        return True

    def _on_unmapped(self, uc, access, address, size, value, ud):
        # map on demand so stray accesses don't abort the run
        try:
            page = address & ~0xFFF
            uc.mem_map(page, 0x1000)
            return True
        except Exception:
            return False

    def call(self, addr, args=(), count=2_000_000):
        uc = self.uc
        for i, v in enumerate(args[:4]):
            uc.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3][i], v & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.tx.clear(); self.mem_writes.clear(); self.calls.clear()
        # keep USART SR ready during the run via a read hook
        def _rd(uc_, access, address, size, value, ud):
            base = address & ~0xFF
            if base in USARTS and (address & 0xFF) == 0x00:
                uc_.mem_write(base, struct.pack("<I", USART_SR_READY))
        h = uc.hook_add(UC_HOOK_MEM_READ, _rd, begin=PERIPH, end=PERIPH+PERIPH_SZ)
        try:
            uc.emu_start((addr & ~1) | 1, STOP, count=count)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            if (pc & ~1) != STOP:        # STOP = clean return via LR sentinel
                print(f"  [emu stopped: {e} at pc=0x{pc:08x}]")
        finally:
            uc.hook_del(h)
        return uc.reg_read(UC_ARM_REG_R0)

    def w32(self, a, v): self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
    def wbytes(self, a, b): self.uc.mem_write(a, bytes(b))
    def r32(self, a): return struct.unpack("<I", self.uc.mem_read(a, 4))[0]
    def rbytes(self, a, n): return bytes(self.uc.mem_read(a, n))


# ---- self-test: compute Modbus CRC-16 in-firmware ---------------------------
def modbus_crc(buf):
    crc = 0xFFFF
    for b in buf:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--symbols", default="reference/symbols_named.csv")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--call", help="hex address to call")
    ap.add_argument("--args", default="", help="comma-separated hex args")
    args = ap.parse_args()

    emu = Emu(args.image, args.symbols)

    if args.selftest:
        scratch = RAM_BASE + 0x8000
        emu.wbytes(scratch, b"123456789")
        want = modbus_crc(b"123456789")
        print(f"expected Modbus CRC('123456789') = 0x{want:04x}")
        for name, addr, sig in [("sub_08000d98(buf,len)", 0x08000d98, (scratch, 9)),
                                ("sub_08000de4(buf,len)", 0x08000de4, (scratch, 9))]:
            r = emu.call(addr, sig) & 0xFFFF
            ok = "  <== MATCH" if r == want else ""
            print(f"  {name} -> 0x{r:04x}{ok}")
    elif args.call:
        a = int(args.call, 16)
        aa = [int(x, 16) for x in args.args.split(",") if x.strip()]
        r = emu.call(a, aa)
        print(f"call 0x{a:08x} -> r0=0x{r:08x}")
        if emu.tx:
            print("UART TX captured:")
            from collections import defaultdict
            per = defaultdict(list)
            for u, b in emu.tx: per[u].append(b)
            for u, bs in per.items():
                print(f"  {u}: {' '.join(f'{x:02x}' for x in bs)}")
        else:
            print("UART TX captured: (none)")
