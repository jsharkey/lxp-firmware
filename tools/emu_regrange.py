#!/usr/bin/env python3
"""Emulate a DSP-side holding-register group READ through the ARM frame builder
sub_08014fec and capture the response frame layout, mapping each register to its
frame byte offset.

The ARM<->DSP link reads holding registers in fixed groups of 40 (0-39, 40-79,
80-119; EG4 spec s2.9). Response frame: addr, func, SN[0..9] (0x02-0x0b), start
reg (LE @0x0c), byte count (LE @0x0e), then register values at 0x10+, 2 bytes
each in register order -- so register N -> frame offset 0x10 + (N-start)*2. This
is how regs 64-89 (battery charge/discharge schedule) reach the DSP (docs/08).
Read-only; executes the image in a sandbox.

Usage: python3 tools/emu_regrange.py            # group 40-79 (holds regs 64-79)
"""
import sys, struct
sys.path.insert(0,"tools")
from emu import Emu

RX=0x20007490; FRAME=0x20009414; BUILDER=0x08014fec
FLAG=0x2000aa0b
SETTINGS=0x20009854; IMG=0x2000691c

def run(start,count,cls=3):
    emu=Emu("reference/ceaa-07xx_vE_260214.bin","reference/symbols.csv")
    emu.wbytes(SETTINGS, bytes([i&0xff for i in range(256)]))
    # seed register image region with a recognizable pattern too
    emu.wbytes(IMG, bytes([0x55]*0x1000))
    emu.uc.mem_write(FLAG, b"\x00")
    emu.wbytes(RX, bytes(0x100))
    emu.uc.mem_write(RX+0, bytes([0x01, cls]))
    emu.uc.mem_write(RX+0x0c, struct.pack("<H", start))
    emu.uc.mem_write(RX+0x0e, struct.pack("<H", count))
    emu.wbytes(FRAME, bytes([0xEE]*0xC0))
    emu.watch=(FRAME, FRAME+0xC0)
    rv=emu.call(BUILDER, (0, RX, 0x40))
    ws=sorted(set((a-FRAME, v) for (pc,a,sz,v) in emu.mem_writes))
    return rv, ws

rv, ws = run(40,40)
print("builder returned len=0x%x, %d frame bytes written"%(rv&0xffff, len(ws)))
maxoff = max(o for o,_ in ws) if ws else 0
print("frame layout (offset : value):")
for o,v in ws:
    print("  0x%02x = 0x%02x"%(o,v))
