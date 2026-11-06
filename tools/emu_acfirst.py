#!/usr/bin/env python3
"""
AC-First window -> DSP push: a reproducible emulation experiment.

Question (from the register map): Modbus regs 152-157 are the "AC First"
time windows (ACFirstStart/EndHour/Minute). Where do they end up relative to
the config image the ARM pushes to the DSP?

This drives the real firmware in Unicorn (tools/emu.py) and answers it two ways:

  Stage A -- set window 0 = 02:00-04:00 in the settings struct, then sweep the
             emulated ARM RTC across the boundaries and read the derived
             "AC-First active now" status the evaluator produces.

  Stage B -- at an in-window time vs an out-of-window time, run the real
             DSP comms-task builder (sub_0801c11c) and diff ALL of RAM to see
             exactly which bytes the window change affects -- in particular
             whether any byte of a DSP TX frame changes.

Findings (see docs/08):
  * The window is stored at settings(0x20009854)+0x64..0x6e (regs 152-157),
    u16 = (minute<<8)|hour, 3 windows strided by 4 bytes.
  * The ARM evaluates it against its own RTC (0x2000a718: +1 min, +2 hour) in
    sub_0801eb4c: active iff start <= now < end (start-inclusive, end-exclusive).
  * The result is a per-window bit at 0x2000aa5e, aggregated to bit24 of the
    status word 0x2000a758 and mirrored to bit4 (0x10) of 0x2000a8e6.
  * In a cold builder run the window affects ONLY those derived-status bytes
    (plus a stack scratch holding minutes-of-day) -- no DSP TX frame byte
    changes. The windows are evaluated ARM-side, not pushed as frame data.

Read-only: executes the flat image in a sandbox; touches no hardware.
Usage: python3 tools/emu_acfirst.py            # from repo root (needs reference/ceaa-05xx_com_vE_250325.bin)
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from emu import Emu
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

IMG = os.environ.get("ACF_IMG", "reference/ceaa-05xx_com_vE_250325.bin")
SYM = os.environ.get("ACF_SYM", "reference/symbols.csv")

SETTINGS = 0x20009854
RTC      = 0x2000a718          # byte +1 = minute, byte +2 = hour (as read by sub_0801eb4c)
WIN_TIMER= 0x2000a98c          # debounce counter at the evaluator's top; 0 => evaluate now
ST_WIN   = 0x2000aa5e          # per-window "inside now" bitmask (bit i = window i)
ST_WORD  = 0x2000a758          # system status word; bit24 = any AC-First window active
ST_HALF  = 0x2000a8e6          # status halfword; bit4 (0x10) mirrors the above
EVAL_CALLER = 0x0801ece8       # calls the evaluator sub_0801eb4c, then mirrors bit24 -> a8e6 bit4
BUILDER     = 0x0801c11c       # the scheduler-registered DSP comms-task builder
SEND        = 0x0801c370       # send-frame helper: sub_0801c370(ptr, len) -> USART3 TX

def enc(hour, minute): return ((minute & 0xff) << 8) | (hour & 0xff)

def _seed(emu, hour, minute):
    emu.wbytes(SETTINGS + 0x60, bytes(0x20))                       # clear window region
    emu.uc.mem_write(SETTINGS + 0x64, struct.pack("<H", enc(2, 0)))  # window0 start 02:00
    emu.uc.mem_write(SETTINGS + 0x66, struct.pack("<H", enc(4, 0)))  # window0 end   04:00
    emu.uc.mem_write(SETTINGS + 0x0b, struct.pack("<H", 0x0100))    # enable config paths
    emu.uc.mem_write(SETTINGS + 0x1a, bytes([0x01]))
    emu.wbytes(RTC, bytes(8))
    emu.uc.mem_write(RTC + 1, bytes([minute & 0xff]))
    emu.uc.mem_write(RTC + 2, bytes([hour & 0xff]))
    emu.w32(WIN_TIMER & ~1, 0)

def stage_a():
    print("=== Stage A: window0 = 02:00-04:00, sweep the RTC ===")
    print("start u16=0x%04x @+0x64, end u16=0x%04x @+0x66\n" % (enc(2,0), enc(4,0)))
    print("%-6s %-5s | aa5e | a758.b24 | a8e6.b4 | verdict" % ("RTC","min"))
    print("-"*58)
    for h,m in [(1,30),(1,59),(2,0),(2,1),(3,0),(3,59),(4,0),(4,1),(5,0),(0,0)]:
        emu = Emu(IMG, SYM)
        _seed(emu, h, m)
        emu.uc.mem_write(ST_WIN, b"\x00"); emu.w32(ST_WORD,0); emu.w32(ST_HALF & ~1,0)
        emu.call(EVAL_CALLER)
        wm   = emu.rbytes(ST_WIN,1)[0]
        b24  = (emu.r32(ST_WORD)>>24)&1
        b4   = (struct.unpack("<H",emu.rbytes(ST_HALF,2))[0]>>4)&1
        print("%02d:%02d  %4d  | 0x%02x |    %d     |    %d    | %s" % (
            h,m,h*60+m,wm,b24,b4,"ACTIVE" if wm&1 else "off"))

def _run_builder(hour, minute):
    emu = Emu(IMG, SYM)
    _seed(emu, hour, minute)
    sends=[]
    def on_send(uc, addr, size, ud):
        ptr=uc.reg_read(UC_ARM_REG_R0); ln=uc.reg_read(UC_ARM_REG_R1)&0xffff
        try: b=bytes(uc.mem_read(ptr, min(ln,256)))
        except Exception: b=b""
        sends.append((ptr,ln,b))
    emu.uc.hook_add(UC_HOOK_CODE, on_send, begin=SEND & ~1, end=(SEND & ~1)+2)
    emu.call(EVAL_CALLER)
    emu.call(BUILDER)
    ram = emu.rbytes(0x20000000, 0x10000)
    return ram, sends

def stage_b():
    print("\n=== Stage B: run the DSP comms-task builder, diff ALL RAM (in vs out) ===")
    ina, sa = _run_builder(3,0)
    outb, sb = _run_builder(5,0)
    KNOWN={0x2000a71a:"RTC.hour",0x2000aa5e:"aa5e win-mask",
           0x2000a75b:"a758.byte3 (bit24)",0x2000a8e6:"a8e6 (bit4)"}
    diffs=[(0x20000000+i, ina[i], outb[i]) for i in range(len(ina)) if ina[i]!=outb[i]]
    for addr,x,y in diffs:
        tag=KNOWN.get(addr,"")
        if 0x20009414<=addr<0x20009460: tag=tag or ">>> block-0 DSP frame"
        if 0x20009053<=addr<0x200090a0: tag=tag or ">>> DSP frame #2"
        if 0x20009754<=addr<0x200097a0: tag=tag or ">>> DSP frame #3"
        if 0x2000fb00<=addr<0x2000fc00: tag=tag or "(stack scratch)"
        print("  0x%08x : IN=0x%02x OUT=0x%02x   %s" % (addr,x,y,tag))
    print("  sends during build: IN=%d OUT=%d" % (len(sa),len(sb)))
    frame=[d for d in diffs if 0x20009048<=d[0]<0x20009800]
    print("  --> differing bytes inside any DSP TX frame / comms struct: %d" % len(frame))

if __name__ == "__main__":
    if not os.path.exists(IMG):
        sys.exit("need %s (run tools/hex2bin.py on the ARM .hex first)" % IMG)
    stage_a()
    stage_b()
