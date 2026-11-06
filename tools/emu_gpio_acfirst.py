#!/usr/bin/env python3
"""
Does the ARM toggle a GPIO relay when the "AC First" window goes active?

Background (docs/08): the AC-First load-priority windows (Modbus regs 152-157)
are *not* pushed to the DSP. The ARM evaluates them against its own RTC in
sub_0801eb4c and the result flows window -> 0x2000aa5e -> bit24 of 0x2000a758 ->
bit4 of 0x2000a8e6, which a static reader-enumeration found ends in app/dongle
*telemetry*, not a control output. A standing theory is that the ARM might
instead drive an AC/grid relay GPIO directly from that decision -- a path a
call-graph cannot show, because a relay toggle is a memory store to a GPIO
register (BSRR/BRR/ODR), not a call edge.

This probe closes that gap *dynamically*. It extends the Unicorn harness
(tools/emu.py) to capture every write to an STM32F103 GPIO port while the
AC-First evaluator and the surrounding mode/status supervisor run, at an
in-window RTC vs an out-of-window RTC, and diffs them. If the ARM switched a
relay on the AC-First decision, a GPIO bit would differ between the two runs.

  Stage A -- run just the evaluator caller (sub_0801ece8).
  Stage B -- run the mode/status supervisor (sub_0801f184), which fans out to
             the whole status-computation cluster (e608/ece8/ed28/eeb0/effa/
             f11c); a relay update driven off the derived mode is far more
             likely to live in that pass than in the narrow evaluator.

A GPIO write is reported as window-dependent only if its (port, register,
value) set differs between the in-window and out-of-window runs. Pins that
toggle identically in both runs are housekeeping (LCD refresh, RS-485 DE,
keypad scan, fan/LED PWM) and are *not* the AC-First relay.

Read-only: executes the flat image in a sandbox; touches no hardware.
Usage:  python3 tools/emu_gpio_acfirst.py      # from repo root (needs reference/ceaa-05xx_com_vE_250325.bin)

Honest caveat (same as emu_acfirst.py): sub_0801f184 is a gated scheduler task;
a cold single-pass run does not exercise every branch. A null result here
proves no relay is toggled along the paths a cold run reaches -- it corroborates
the static enumeration in docs/08, it does not replace an on-hardware check.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from emu import Emu
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC

IMG = os.environ.get("ACF_IMG", "reference/ceaa-05xx_com_vE_250325.bin")
SYM = os.environ.get("ACF_SYM", "reference/symbols.csv")

SETTINGS = 0x20009854
RTC      = 0x2000a718          # byte +1 = minute, byte +2 = hour
WIN_TIMER= 0x2000a98c          # debounce counter; 0 => evaluate now
EVAL_CALLER = 0x0801ece8       # evaluator caller (window -> a758 bit24 -> a8e6 bit4)
SUPERVISOR  = 0x0801f184       # mode/status supervisor; calls the whole cluster

# STM32F103 GPIO ports: 0x40010800 + port*0x400, ports A..G.
GPIO_LO = 0x40010800
GPIO_HI = 0x40012400           # one past GPIOG
GPIO_REG = {0x00:"CRL", 0x04:"CRH", 0x08:"IDR", 0x0c:"ODR",
            0x10:"BSRR", 0x14:"BRR", 0x18:"LCKR"}
# Writes that actually change an output level (i.e. could switch a relay):
DRIVE_REGS = {"ODR", "BSRR", "BRR"}

def _port(base):
    return "GPIO" + chr(ord('A') + (base - GPIO_LO) // 0x400)

def enc(hour, minute):
    return ((minute & 0xff) << 8) | (hour & 0xff)

def _seed(emu, hour, minute):
    emu.wbytes(SETTINGS + 0x60, bytes(0x20))                         # clear window region
    emu.uc.mem_write(SETTINGS + 0x64, struct.pack("<H", enc(2, 0)))  # window0 start 02:00
    emu.uc.mem_write(SETTINGS + 0x66, struct.pack("<H", enc(4, 0)))  # window0 end   04:00
    emu.uc.mem_write(SETTINGS + 0x0b, struct.pack("<H", 0x0100))     # enable config paths
    emu.uc.mem_write(SETTINGS + 0x1a, bytes([0x01]))
    emu.wbytes(RTC, bytes(8))
    emu.uc.mem_write(RTC + 1, bytes([minute & 0xff]))
    emu.uc.mem_write(RTC + 2, bytes([hour & 0xff]))
    emu.w32(WIN_TIMER & ~1, 0)

def _capture(entry, hour, minute):
    """Run `entry` with the RTC seeded; return the set of GPIO level-drive writes."""
    emu = Emu(IMG, SYM)
    _seed(emu, hour, minute)
    writes = []          # (pc, port, reg, value)
    def on_gpio(uc, access, address, size, value, ud):
        base = address & ~0x3FF
        off  = address & 0x3FF
        if GPIO_LO <= base < GPIO_HI and off in GPIO_REG:
            writes.append((uc.reg_read(UC_ARM_REG_PC), _port(base),
                           GPIO_REG[off], value & 0xFFFFFFFF))
        return True
    emu.uc.hook_add(UC_HOOK_MEM_WRITE, on_gpio, begin=GPIO_LO, end=GPIO_HI)
    emu.call(entry)
    # the level-affecting writes are what could switch a relay
    drive = {(p, r, v) for (_pc, p, r, v) in writes if r in DRIVE_REGS}
    return writes, drive

def _run(name, entry):
    print("=== %s: entry sub_%08x, window0 = 02:00-04:00 ===" % (name, entry))
    allw_in,  drive_in  = _capture(entry, 3, 0)    # 03:00 -> inside window
    allw_out, drive_out = _capture(entry, 5, 0)    # 05:00 -> outside window
    print("  GPIO writes total: IN(03:00)=%d  OUT(05:00)=%d" % (len(allw_in), len(allw_out)))
    print("  distinct level-drive (ODR/BSRR/BRR) sets: IN=%d OUT=%d"
          % (len(drive_in), len(drive_out)))
    only_in  = drive_in  - drive_out
    only_out = drive_out - drive_in
    if not only_in and not only_out:
        print("  --> NO window-dependent GPIO level write. "
              "No relay is toggled by the AC-First decision on this path.\n")
        return
    print("  --> WINDOW-DEPENDENT GPIO WRITES (candidate AC-First relay):")
    for (p, r, v) in sorted(only_in):
        print("        only IN-window : %s->%s = 0x%08x" % (p, r, v))
    for (p, r, v) in sorted(only_out):
        print("        only OUT-window: %s->%s = 0x%08x" % (p, r, v))
    print()

if __name__ == "__main__":
    if not os.path.exists(IMG):
        sys.exit("need %s (run tools/hex2bin.py on the ARM .hex first)" % IMG)
    _run("Stage A -- evaluator caller", EVAL_CALLER)
    _run("Stage B -- mode/status supervisor", SUPERVISOR)
