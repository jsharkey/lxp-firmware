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
from unicorn.arm_const import *

# Cortex-M registers the hardware stacks on exception entry (R0-R3, R12, LR, PC,
# xPSR) plus the callee-saved ones -- we save/restore all of them around an
# injected SysTick handler so it is transparent to the interrupted code.
_SYSTICK_SAVE = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                 UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                 UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
                 UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
                 UC_ARM_REG_CPSR]
SYST_CSR = 0xE000E010          # SysTick control/status: b0 ENABLE, b1 TICKINT, b16 COUNTFLAG
SCB_VTOR = 0xE000ED08          # vector table base
SCB_ICSR = 0xE000ED04          # interrupt control/state: b28 PENDSVSET, b26 PENDSTSET
EXC_BASE = 0xFFFFF000          # a mapped page so EXC_RETURN (0xFFFFFFFx) fetches are catchable
EXC_RET_MSP    = 0xFFFFFFF9    # return to thread, MSP
EXC_RET_PSP    = 0xFFFFFFFD    # return to thread, PSP
EXC_RET_HANDLER= 0xFFFFFFF1    # return to handler
EXC_SYSTICK = 15
EXC_PENDSV  = 14
EXC_SVC     = 11

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
SPI_DR = 0x0C                  # SPI data register offset


class SpiNorFlash:
    """Minimal SPI NOR flash slave (W25Q-style), RAM-backed, starts erased
    (0xFF). Enough of the command set for the factory's boot-time config-flash
    bring-up: read, program, erase, read/write status, WREN, JEDEC id. One SPI
    byte = one xfer(mosi)->miso; cs_change() frames commands."""
    def __init__(self, size=0x200000, jedec=(0xEF, 0x40, 0x15)):  # 2 MB, W25Q16-ish
        self.mem = bytearray(b"\xFF" * size)
        self.size = size
        self.jedec = bytes(jedec)
        self.wel = 0
        self.cmd = bytearray()

    def cs_change(self, asserted):
        self.cmd = bytearray()           # (de)assert both start a fresh command

    def _addr(self):
        return ((self.cmd[1] << 16) | (self.cmd[2] << 8) | self.cmd[3]) % self.size

    def xfer(self, mosi):
        self.cmd.append(mosi & 0xFF)
        op = self.cmd[0]
        pos = len(self.cmd) - 1          # 0 = opcode byte
        if op == 0x06:                   # WREN
            self.wel = 1; return 0xFF
        if op == 0x04:                   # WRDI
            self.wel = 0; return 0xFF
        if op == 0x05:                   # RDSR1: status (WIP=0 -> ready) | WEL
            return (self.wel << 1) if pos >= 1 else 0xFF
        if op == 0x35 or op == 0x15:     # RDSR2/3
            return 0x00
        if op == 0x9F:                   # JEDEC id
            return self.jedec[pos - 1] if 1 <= pos <= 3 else 0xFF
        if op in (0x03, 0x0B):           # READ (0x0B fast-read has 1 dummy byte)
            dummy = 1 if op == 0x0B else 0
            first = 4 + dummy
            if pos >= first:
                a = (self._addr() + (pos - first)) % self.size
                return self.mem[a]
            return 0xFF
        if op == 0x02:                   # PAGE PROGRAM
            if pos >= 4 and self.wel:
                a = (self._addr() + (pos - 4)) % self.size
                self.mem[a] = mosi & 0xFF
            return 0xFF
        if op in (0x20, 0x52, 0xD8):     # sector/block erase (4K/32K/64K)
            span = {0x20: 0x1000, 0x52: 0x8000, 0xD8: 0x10000}[op]
            if pos == 3 and self.wel:
                base = (self._addr() // span) * span
                self.mem[base:base + span] = b"\xFF" * span
                self.wel = 0
            return 0xFF
        if op in (0xC7, 0x60):           # chip erase
            if self.wel:
                self.mem = bytearray(b"\xFF" * self.size); self.wel = 0
            return 0xFF
        return 0xFF

# --- config-flash records -------------------------------------------------
# The factory com-MCU keeps its settings in a journaled store on the SPI NOR
# config flash: six 8 KB regions (slot N at N*CONFIG_REGION), each a ring of
# 256-byte records. A record is 250 payload bytes, a 16-bit Modbus CRC of that
# payload at [0xFA:0xFC] (little-endian), and a 0xA5 "written" marker at [0xFF];
# the firmware scans a region newest-first (highest address down) and takes the
# first record whose marker and CRC check out. If a slot has none, it falls back
# to a compiled-in default record in the MCU's own flash (0x0807F800 for slot 0,
# 0x0807F900 for slot 5). A blank chip with those defaults absent leaves boot
# stuck re-scanning, so a harness must present valid config to get past bring-up
# -- see attach_config_flash(). (Reverse-engineered from the ceaa-07xx image:
# scan sub_0801_6652, CRC sub_0801_60bc == the repo's Modbus CRC-16.)
CONFIG_RECORD = 0x100          # one record / flash page
CONFIG_REGION = 0x2000         # per-slot region size (32 records)
CONFIG_SLOTS  = 6              # slots 0..5
CONFIG_MARKER = 0xA5           # [0xFF] "record written" marker
CONFIG_CRC_OFF = 0xFA          # [0xFA:0xFC] little-endian payload CRC
CONFIG_PAYLOAD = 0xFA          # bytes [0:0xFA] covered by the CRC

def config_crc16(data):
    """Modbus CRC-16 (poly 0xA001, init 0xFFFF) -- the checksum the factory
    firmware validates each config record against (and the same CRC the repo's
    src/modbus uses)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF

def make_config_record(payload=b""):
    """Build one valid 256-byte config record from up to 250 payload bytes
    (zero-padded): payload + CRC16(payload) at 0xFA + marker 0xA5 at 0xFF. The
    firmware accepts it (marker + CRC), so default/blank payload is enough to
    clear the config gate; fill the payload to drive specific settings."""
    payload = bytes(payload)
    if len(payload) > CONFIG_PAYLOAD:
        raise ValueError("payload > %d bytes" % CONFIG_PAYLOAD)
    rec = bytearray(b"\x00" * CONFIG_RECORD)
    rec[:len(payload)] = payload
    crc = config_crc16(rec[:CONFIG_PAYLOAD])
    rec[CONFIG_CRC_OFF] = crc & 0xFF
    rec[CONFIG_CRC_OFF + 1] = (crc >> 8) & 0xFF
    rec[CONFIG_RECORD - 1] = CONFIG_MARKER
    return bytes(rec)

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
        # "addr type name" for defined symbols (code t/T/w/W and data b/d/r/...);
        # undefined symbols have only "type name" and are skipped.
        if len(p) == 3:
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
        self._tick_interval = None             # SysTick off until enable_systick()
        self._halt = False                     # set by stop-hooks so the tick driver breaks
        self._rtos = False                     # RTOS exception engine off until enable_rtos()
        self._exc_depth = 0                    # 0 = thread mode, >0 = in handler(s)
        self._systick_due = False              # a SysTick is pending (deferred while masked)
        self._rtos_step = 2000                 # run quantum between exception checks (RTOS)
        self._thread_on_psp = False            # True while a task (PSP) is the interrupted thread
        self._msp = None                       # shadow main/handler stack (see _exc_entry)
        self._insns = 0                        # instructions executed this RTOS run (block hook)
        self._tick_mark = 0                    # next _insns value at which a SysTick comes due
        self._pending_irqs = []                # peripheral IRQ vector numbers awaiting delivery
        self._pendsv_set = False               # mirror of ICSR.PENDSVSET (cheap flag for the block hook)
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
        # The factory com-MCU executes ARMv7E-M DSP instructions (smlabb, sdiv, …)
        # with STM32F1-compatible peripherals -- i.e. an M4-class core (a GD32F303-
        # style F1 clone), not a true Cortex-M3. Use an M4 model so those decode;
        # our own M3-built firmware runs on it unchanged (M4 is a superset).
        for m in ("UC_CPU_ARM_CORTEX_M4", "UC_CPU_ARM_CORTEX_M33", "UC_CPU_ARM_CORTEX_M7"):
            mv = globals().get(m)
            if mv is not None:
                try: uc.ctl_set_cpu_model(mv); break
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
        # Scope the STOP-sentinel code hook to the STOP page only. Every run path
        # stops at STOP via emu_start's native `until` (call/_run_rtos/_fire_systick
        # all pass STOP; the one no-`until` path, a from-reset boot, never reaches
        # STOP), so this hook never needs to fire on ordinary instructions — and a
        # code hook that fires on *every* instruction is the dominant per-step cost
        # (a full factory boot more than halves without it).
        uc.hook_add(UC_HOOK_CODE, self._on_code, begin=STOP, end=STOP + 0x1000)
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
        elif base == RCC and off == 0x20:                    # RCC_BDCR: LSE ready (RTC crystal)
            cur = struct.unpack("<I", uc.mem_read(RCC+0x20, 4))[0]
            uc.mem_write(RCC+0x20, struct.pack("<I", cur | (1 << 1)))
        elif base == RCC and off == 0x24:                    # RCC_CSR: LSI ready
            cur = struct.unpack("<I", uc.mem_read(RCC+0x24, 4))[0]
            uc.mem_write(RCC+0x24, struct.pack("<I", cur | (1 << 1)))
        elif addr == 0x40002804:                             # RTC_CRL: RSF synced + RTOFF ready
            cur = struct.unpack("<I", uc.mem_read(0x40002804, 4))[0]
            uc.mem_write(0x40002804, struct.pack("<I", cur | (1 << 3) | (1 << 5)))
        elif base in (0x40013000, 0x40003800) and off == 0x08:   # SPI1/SPI2_SR: TXE|RXNE, not BSY
            uc.mem_write(base + 0x08, struct.pack("<I", (1 << 1) | (1 << 0)))
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

    # ---- SPI NOR flash device (opt-in) ----------------------------------
    def attach_spi_flash(self, cs_pin="PA4", spi_base=0x40013000, flash=None):
        """Attach a RAM-backed SPI NOR flash on `spi_base`, chip-selected by
        `cs_pin` (active low). The factory boots a config/settings flash on SPI1;
        without a responding device it loops re-initialising. Returns the device
        (its .mem is the backing store). Opt-in -- off unless called."""
        dev = flash or SpiNorFlash()
        self.spi_flash = dev
        dr = spi_base + SPI_DR
        port, bit = parse_pin(cs_pin)
        pending = [0xFF]
        def on_cs(uc, access, addr, size, value, ud):
            off = addr - GPIO[port]
            asserted = None
            if off == R_BSRR:
                if (value >> bit) & 1: asserted = False            # set high -> deassert
                elif (value >> (16 + bit)) & 1: asserted = True    # reset low -> assert
            elif off == R_BRR and (value >> bit) & 1: asserted = True
            elif off == R_ODR: asserted = not ((value >> bit) & 1)
            if asserted is not None: dev.cs_change(asserted)
            return True
        self.uc.hook_add(UC_HOOK_MEM_WRITE, on_cs, begin=GPIO[port], end=GPIO[port] + 0x18)
        def on_dr_w(uc, access, addr, size, value, ud):
            pending[0] = dev.xfer(value & 0xFF); return True
        def on_dr_r(uc, access, addr, size, value, ud):
            uc.mem_write(dr, struct.pack("<I", pending[0])); return True
        self.uc.hook_add(UC_HOOK_MEM_WRITE, on_dr_w, begin=dr, end=dr + 4)
        self.uc.hook_add(UC_HOOK_MEM_READ, on_dr_r, begin=dr, end=dr + 4)
        return dev

    def attach_config_flash(self, cs_pin="PA4", spi_base=0x40013000,
                            slots=CONFIG_SLOTS, payloads=None):
        """Attach an SPI NOR config flash already provisioned with valid config,
        the way a factory-programmed board presents it. Writes one valid record
        (make_config_record) at the top page of each slot region so the firmware
        finds valid config for every slot on the first read, instead of scanning
        a blank chip forever. This clears the config bring-up gate and lets boot
        reach task creation and the scheduler.

        `payloads`: optional {slot: payload-bytes} to drive specific settings;
        slots not listed get a blank (all-zero) but validly-framed record.
        Returns the SpiNorFlash device (its .mem is the backing store)."""
        payloads = payloads or {}
        dev = SpiNorFlash()
        for slot in range(slots):
            top = slot * CONFIG_REGION + (CONFIG_REGION - CONFIG_RECORD)
            dev.mem[top:top + CONFIG_RECORD] = make_config_record(payloads.get(slot, b""))
        return self.attach_spi_flash(cs_pin=cs_pin, spi_base=spi_base, flash=dev)

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

    # ---- SysTick injection (opt-in) -------------------------------------
    def enable_systick(self, interval=20_000):
        """Fire the SysTick interrupt every `interval` emulated instructions.

        This harness has no real timers, so a firmware's tick-driven logic (its
        cooperative scheduler, periodic tasks, our firmware's g_ticks-gated loop)
        otherwise never advances past boot. With SysTick on, runs proceed in
        `interval`-instruction chunks and, between chunks, the SysTick vector
        handler is invoked with full register save/restore -- a precise interrupt
        at a chunk boundary. Off by default (keeps non-tick tests fast)."""
        self._tick_interval = interval
        return self

    def disable_systick(self):
        self._tick_interval = None
        return self

    def _fire_systick(self):
        """Invoke the SysTick handler once, iff SysTick is enabled, its interrupt
        is armed and interrupts are unmasked -- transparently to the running code."""
        uc = self.uc
        csr = self.r32(SYST_CSR)
        if not (csr & 1):                       # ENABLE off
            return
        self.w32(SYST_CSR, csr | (1 << 16))     # COUNTFLAG (for polled timebases)
        if not (csr & 2):                       # TICKINT off -> no interrupt
            return
        if uc.reg_read(UC_ARM_REG_PRIMASK) & 1: # interrupts masked
            return
        vtor = self.r32(SCB_VTOR)
        handler = self.r32((vtor or self.vector_base()) + 0x3C)   # exception 15
        if not handler or handler == 0xFFFFFFFF:
            return
        saved = {r: uc.reg_read(r) for r in _SYSTICK_SAVE}
        uc.reg_write(UC_ARM_REG_LR, STOP | 1)   # return to the STOP sentinel
        try:
            uc.emu_start(handler | 1, STOP, count=1_000_000)
        except UcError:
            pass
        for r, v in saved.items():              # restore the interrupted context
            uc.reg_write(r, v)

    # ---- RTOS exception engine (opt-in) ---------------------------------
    # Unicorn emulates the CPU but not the Cortex-M exception machinery, so to run
    # the factory's preemptive RTOS we model it: exception ENTRY stacks
    # {r0-r3,r12,lr,pc,xpsr} on the active stack (PSP/MSP) and vectors to the
    # handler on MSP; EXC_RETURN (a fetch at 0xFFFFFFFx, caught by a hook) unstacks
    # and returns. SysTick is injected between run-chunks; PendSV is tail-chained
    # whenever a handler returns to thread with PENDSVSET pending. The firmware's
    # own SysTick/PendSV/SVC handlers then do the real scheduling and the
    # FreeRTOS-style context switch (mrs/msr psp + {r4-r11}), which Unicorn's
    # native MSP/PSP banking supports.
    def enable_rtos(self, interval=20_000):
        self._rtos = True
        self._tick_interval = interval
        self._exc_event = None
        try: self.uc.mem_map(EXC_BASE, 0x1000)
        except Exception: pass
        # Unicorn raises UC_HOOK_INTR both for a real `svc` and when execution
        # branches to an EXC_RETURN value (0xFFFFFFFx). The hook only *flags* the
        # event and stops; the _run driver performs the state change and restarts
        # emu_start at the new PC (rewriting PC from inside a hook is unreliable).
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)
        # A per-block hook drives the engine between instructions. It (a) counts
        # real instructions, so the SysTick cadence and run budget stay right
        # however a quantum ends, and (b) stops emulation *promptly* at a block
        # boundary whenever a pending exception may now be taken. (b) is what
        # makes PendSV prompt: the firmware's yield selects the next task (writing
        # cur_id) and sets PENDSVSET inside a critical section, expecting the
        # switch the instant interrupts re-enable. Were it deferred to a fixed
        # quantum, the still-running task would loop back and -- now reading the
        # updated cur_id -- clear the newly selected task's ready bit, draining
        # the ready set so every switch lands on the idle task. Stopping at a
        # block boundary (never mid-instruction, unlike a store hook) is safe: PC
        # is left on a real instruction, so nothing re-executes.
        self.uc.hook_add(UC_HOOK_BLOCK, self._on_block)
        # Track PENDSVSET with a cheap flag set here (ICSR writes are rare) so the
        # per-block hook never has to read ICSR from memory to notice a pending
        # context switch.
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._on_icsr_write,
                         begin=SCB_ICSR, end=SCB_ICSR + 4)
        return self

    def _on_icsr_write(self, uc, access, addr, size, value, ud):
        if value & (1 << 28):                                # PENDSVSET
            self._pendsv_set = True

    def pend_irq(self, vecnum):
        """Pend a peripheral interrupt (vector number, e.g. 16+IRQn) for the RTOS
        engine to deliver as soon as it is in thread mode with interrupts enabled.
        The factory receives the RS485/dongle UART purely by RX interrupt, so a
        harness must pend that IRQ to feed it bytes; polling its SR/DR is never
        done by the firmware. Requires enable_rtos(). Idempotent while the IRQ is
        still queued -- like a real NVIC pending bit, re-asserting a line that is
        already pending does not stack a second delivery (so a drain-all-bytes ISR
        that re-pends per byte produces one delivery, not one per byte)."""
        if vecnum not in self._pending_irqs:
            self._pending_irqs.append(vecnum)
        return self

    def _on_block(self, uc, addr, size, ud):
        # Hot path -- runs on every basic block, so it is kept to a few local
        # operations and makes NO Unicorn calls in the common case (nothing
        # pending). (size >> 1 approximates the thumb instruction count; exactness
        # does not matter for the tick cadence.)
        self._insns += size >> 1
        if self._insns >= self._tick_mark:
            self._systick_due = True
            self._tick_mark = self._insns + self._tick_interval
        if not (self._systick_due or self._pendsv_set or self._pending_irqs):
            return                                           # nothing pending -> done
        # A SysTick is due, a PendSV is set, or an IRQ is queued: stop so
        # _run_rtos can take it (only legal in thread mode with interrupts on).
        if self._exc_depth == 0 and not (uc.reg_read(UC_ARM_REG_PRIMASK) & 1):
            uc.emu_stop()

    # We do NOT rely on Unicorn's CONTROL.SPSEL banking: in practice it does not
    # survive our manual EXC_RETURN, so a handler's `mrs psp` would read a stale
    # value and the context switch would corrupt. Instead we keep CONTROL=0 (one
    # active SP) and switch SP ourselves between the task stack and a shadow MSP
    # (`self._msp`), while keeping the PSP register current for the firmware's
    # `mrs/msr psp`. `self._thread_on_psp` tracks whether the interrupted thread
    # was a task (PSP) rather than depending on CONTROL.
    def _exc_entry(self, vecnum):
        """Model Cortex-M exception entry: hardware-stack the caller's frame on
        the active stack, then run the handler on the (shadow) MSP with an
        EXC_RETURN in LR. Returns False (and halts) if the frame can't be written
        (e.g. an uninitialised task stack)."""
        uc = self.uc
        vtor = self.r32(SCB_VTOR)
        handler = self.r32((vtor or self.vector_base()) + 4 * vecnum)
        if not handler or handler == 0xFFFFFFFF:
            return False
        if self._msp is None:
            self._msp = uc.reg_read(UC_ARM_REG_SP)   # capture the main stack once
        sp = uc.reg_read(UC_ARM_REG_SP)              # active stack (task PSP, or main MSP)
        xpsr = uc.reg_read(UC_ARM_REG_XPSR)
        align = (sp - 0x20) & 4
        newsp = (sp - 0x20 - align) & 0xFFFFFFFF
        pc = uc.reg_read(UC_ARM_REG_PC)
        vals = [uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1),
                uc.reg_read(UC_ARM_REG_R2), uc.reg_read(UC_ARM_REG_R3),
                uc.reg_read(UC_ARM_REG_R12), uc.reg_read(UC_ARM_REG_LR),
                pc, (xpsr & ~(1 << 9)) | (0x200 if align else 0)]
        try:
            for i, v in enumerate(vals):
                uc.mem_write(newsp + 4 * i, struct.pack("<I", v & 0xFFFFFFFF))
        except UcError:
            self._halt = True; return False                  # bad SP (incomplete init) -> stop, don't crash
        if self._thread_on_psp:                              # interrupted a task: frame on its PSP
            uc.reg_write(UC_ARM_REG_PSP, newsp)              # handler's `mrs psp` reads this
            uc.reg_write(UC_ARM_REG_SP, self._msp)           # handler runs on MSP
            exc = EXC_RET_PSP
        else:                                                # interrupted main thread: stay on MSP
            self._msp = newsp
            uc.reg_write(UC_ARM_REG_SP, newsp)
            exc = EXC_RET_MSP
        self._exc_depth += 1
        uc.reg_write(UC_ARM_REG_LR, exc)
        uc.reg_write(UC_ARM_REG_XPSR, (xpsr & ~0x1FF) | vecnum)    # IPSR = exception number
        uc.reg_write(UC_ARM_REG_PC, handler | 1)
        return True

    def _on_intr(self, uc, intno, ud):
        if not self._rtos:
            return
        pc = uc.reg_read(UC_ARM_REG_PC)
        if 0xFFFFFFF0 <= pc <= 0xFFFFFFFF:                   # EXC_RETURN branch target
            self._exc_event = 0xFFFFFFF0 | ((pc & 0xF) | 1)
        else:                                               # a real svc instruction
            self._exc_event = "svc"
        uc.emu_stop()

    def _do_exc_return(self, exc):
        """Model Cortex-M exception return: unstack {r0-r3,r12,lr,pc,xpsr} and
        resume on the task (PSP) or main (MSP) stack per EXC_RETURN. We swap SP
        ourselves rather than via CONTROL.SPSEL (see _exc_entry)."""
        uc = self.uc
        self._msp = uc.reg_read(UC_ARM_REG_SP)               # handler ran on MSP; snapshot it
        to_psp = (exc == EXC_RET_PSP)
        frame_sp = uc.reg_read(UC_ARM_REG_PSP) if to_psp else self._msp
        f = [struct.unpack("<I", uc.mem_read((frame_sp + 4 * i) & 0xFFFFFFFF, 4))[0]
             for i in range(8)]
        xpsr = f[7]
        newsp = (frame_sp + 0x20 + (4 if (xpsr & 0x200) else 0)) & 0xFFFFFFFF
        ret_pc = f[6]
        if not (FLASH_BASE <= (ret_pc & ~1) < FLASH_BASE + len(self.data)):
            self._halt = True                                # scheduler returned an invalid task
            return                                           # (incomplete init) -> stop, don't crash
        uc.reg_write(UC_ARM_REG_R0, f[0]); uc.reg_write(UC_ARM_REG_R1, f[1])
        uc.reg_write(UC_ARM_REG_R2, f[2]); uc.reg_write(UC_ARM_REG_R3, f[3])
        uc.reg_write(UC_ARM_REG_R12, f[4]); uc.reg_write(UC_ARM_REG_LR, f[5])
        self._exc_depth = max(0, self._exc_depth - 1)
        if to_psp:                                           # resume a task on its PSP stack
            uc.reg_write(UC_ARM_REG_PSP, newsp)
            uc.reg_write(UC_ARM_REG_SP, newsp)
            self._thread_on_psp = True
        else:                                                # resume the main thread on MSP
            self._msp = newsp
            uc.reg_write(UC_ARM_REG_SP, newsp)
            self._thread_on_psp = False
        uc.reg_write(UC_ARM_REG_XPSR, xpsr | (1 << 24))      # keep Thumb bit
        uc.reg_write(UC_ARM_REG_PC, ret_pc | 1)

    def _pendsv_pending(self):
        self._pendsv_set = False                             # consume the block-hook hint
        icsr = self.r32(SCB_ICSR)
        if (icsr & (1 << 28)) and self._exc_depth == 0:
            self.w32(SCB_ICSR, icsr & ~(1 << 28))
            return True
        return False

    def _run(self, start_pc, max_insn):
        """Run from start_pc for up to max_insn instructions. With SysTick enabled,
        chunk execution and fire the handler between chunks; stop early on a
        stop-hook (self._halt) or the STOP sentinel. With the RTOS engine on, the
        chunk loop also services exception entry/return events."""
        uc = self.uc
        self._halt = False
        if not self._tick_interval:
            try:
                uc.emu_start(start_pc & ~1 | 1, 0xFFFFFFFF, count=max_insn)
            except UcError:
                pass
            return self
        if self._rtos:
            return self._run_rtos(start_pc, max_insn)
        uc.reg_write(UC_ARM_REG_PC, start_pc & ~1 | 1)
        remaining = max_insn
        while remaining > 0 and not self._halt:
            pc = uc.reg_read(UC_ARM_REG_PC)
            self._exc_event = None
            try:
                uc.emu_start(pc | 1, STOP, count=min(self._tick_interval, remaining))
            except UcError:
                pass
            if self._halt or (uc.reg_read(UC_ARM_REG_PC) & ~1) == STOP:
                break
            remaining -= self._tick_interval
            self._fire_systick()
        return self

    def _run_rtos(self, start_pc, max_insn):
        """Event-driven run for the preemptive RTOS. Models the NVIC for the two
        lowest-priority exceptions the port uses -- SysTick (periodic) and PendSV
        (set via PENDSVSET) -- which fire only in thread mode with interrupts
        enabled (PRIMASK clear), and never nest. Execution advances in small
        quanta; between quanta a *pending* exception is taken when it is allowed
        to be, and a SysTick that comes due while interrupts are masked is
        deferred (it collapses to one pending tick, as the real COUNTFLAG does),
        not dropped -- so ticks keep advancing through the firmware's critical
        sections instead of being lost at a chunk boundary that lands in one."""
        uc = self.uc
        uc.reg_write(UC_ARM_REG_PC, start_pc & ~1 | 1)
        self._insns = 0
        self._tick_mark = self._tick_interval
        self._systick_due = False
        step = min(self._tick_interval, self._rtos_step)
        while self._insns < max_insn and not self._halt:
            # Take a pending exception iff in thread mode with interrupts enabled
            # (both SysTick and PendSV sit at the lowest priority, so neither
            # preempts the other or a running handler). A SysTick that comes due
            # while interrupts are masked stays pending (one tick, like the real
            # COUNTFLAG) rather than being dropped.
            if self._exc_depth == 0 and not (uc.reg_read(UC_ARM_REG_PRIMASK) & 1):
                # Peripheral IRQs (e.g. a UART RX) sit above SysTick/PendSV, so
                # deliver a pending one first. pend_irq() queues them.
                if self._pending_irqs and self._exc_entry(self._pending_irqs[0]):
                    self._pending_irqs.pop(0); continue
                if self._systick_due:
                    csr = self.r32(SYST_CSR)
                    self._systick_due = False
                    if csr & 1:                              # ENABLE: latch COUNTFLAG
                        self.w32(SYST_CSR, csr | (1 << 16))
                        if (csr & 2) and self._exc_entry(EXC_SYSTICK):   # TICKINT
                            continue
                if self._pendsv_pending() and self._exc_entry(EXC_PENDSV):
                    continue
            self._exc_event = None
            pc = uc.reg_read(UC_ARM_REG_PC)
            # Run a quantum; the block hook stops us early at a safe boundary the
            # moment a pending exception becomes takeable (e.g. a yield's PendSV
            # right after its crit-exit), so the switch happens before the task
            # runs on.
            n = min(step, max_insn - self._insns)
            try:
                uc.emu_start(pc | 1, STOP, count=max(1, n))
            except UcError:
                pass
            if self._halt or (uc.reg_read(UC_ARM_REG_PC) & ~1) == STOP:
                break
            ev = self._exc_event
            if ev == "svc":
                self._exc_entry(EXC_SVC)
            elif ev is not None:                             # an EXC_RETURN fetch
                self._do_exc_return(ev)
            # else: quantum elapsed or ICSR stop -> loop re-evaluates pending excs
        return self

    def run_reset(self, max_insn=500_000, vector_base=None):
        """Boot from the image's own reset vector and run its event loop for up
        to max_insn instructions (black box: no entry address needed). A bounded
        boot stops wherever it is in the loop; callers assert on observed IO."""
        base = self.vector_base() if vector_base is None else vector_base
        self.uc.reg_write(UC_ARM_REG_SP, self.r32(base))
        return self._run(self.r32(base + 4), max_insn)

    # ---- snapshot / restore (warm once, clone per test, hermetically) ------
    def snapshot(self):
        """Capture the full machine state (CPU context + every mapped memory
        region + the GPIO shadow). restore() returns to exactly this point, so a
        firmware can be warmed once and each test branched from an identical,
        hermetic copy without re-booting."""
        regions = [(b, e - b + 1) for (b, e, _p) in self.uc.mem_regions()]
        return {
            "ctx": self.uc.context_save(),
            "mem": [(b, s, bytes(self.uc.mem_read(b, s))) for (b, s) in regions],
            "regions": set(regions),
            "shadow": dict(self.shadow),
            "drives": list(self.drive_log),
        }

    def restore(self, snap):
        """Reset to a snapshot()."""
        for (b, e, _p) in self.uc.mem_regions():          # drop pages mapped since
            if (b, e - b + 1) not in snap["regions"]:
                try: self.uc.mem_unmap(b, e - b + 1)
                except Exception: pass
        for (b, s, data) in snap["mem"]:
            self.uc.mem_write(b, data)
        self.uc.context_restore(snap["ctx"])
        self.shadow = dict(snap["shadow"])
        self.drive_log = list(snap["drives"])
        return self

    def run(self, max_insn):
        """Resume execution from the current PC for up to max_insn instructions
        (use after restore(); does not reset). Honors SysTick if enabled."""
        return self._run(self.uc.reg_read(UC_ARM_REG_PC), max_insn)

    def run_until_input_read(self, pin, max_insn=8_000_000, vector_base=None):
        """Boot and stop the moment the firmware's loop first reads `pin`'s port
        (its IDR) -- i.e. the first time it samples that input. The natural warm
        point for an input->output behaviour: boot is done, the loop is about to
        look at the pin, and it is reached the same way regardless of the pin's
        eventual level (boot doesn't depend on it)."""
        ip, _ = parse_pin(pin)
        idr = GPIO[ip] + R_IDR
        def _stop(uc, access, addr, size, value, ud):
            uc.emu_stop()
        h = self.uc.hook_add(UC_HOOK_MEM_READ, _stop, begin=idr, end=idr + 4)
        try:
            self.run_reset(max_insn=max_insn, vector_base=vector_base)
        finally:
            self.uc.hook_del(h)
        return self

    def run_until_output(self, out_pin, level=1, settle_input=None,
                         settle_reads=40, max_insn=8_000_000, vector_base=None,
                         reset=True):
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
                self._halt = True       # stop the tick driver too
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
                    self._halt = True
                    uc.emu_stop()
            hooks.append(self.uc.hook_add(UC_HOOK_MEM_READ, _stop_on_settle,
                                          begin=idr, end=idr + 4))
        try:
            if reset:
                self.run_reset(max_insn=max_insn, vector_base=vector_base)
            else:
                self.run(max_insn)        # resume from a restored warm state
        finally:
            for h in hooks:
                self.uc.hook_del(h)
        return self.was_driven(out_pin, level=level)
