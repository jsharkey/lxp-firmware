#!/usr/bin/env python3
"""
Probe the ARM->DSP frame builder sub_08014fec by emulation.

sub_08014fec builds the 0x20009414 response frame from the USART3 RX buffer
(0x20007490): it reads a class byte at [RX+1] and dispatches to a serializer
(sub_0803373c for classes 3/4, sub_08033bb4, or fn_NOTB). This probe seeds the
ARM settings struct so settings[i]==i, issues a request of a given class, and
captures every byte written into the frame region as (frame_offset -> value),
so a value equal to a settings offset reveals a settings->frame copy.

Finding so far: a class-3 request emits a header whose 10-byte SN at frame
offset 0x02 is copied from settings+0x01; the block payload past the header is a
Modbus-style register-range read from the register-value image at 0x2000691c
(see docs/08). Read-only; executes the image in a sandbox.

Usage: python3 tools/emu_frame_probe.py [class ...]   # default classes 3 4
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from emu import Emu

SETTINGS=0x20009854; RX=0x20007490; FRAME=0x20009414; BUILDER=0x08014fec

def probe(cls, length=0x40):
    emu=Emu("reference/com_flat.bin","reference/symbols.csv")
    emu.wbytes(SETTINGS, bytes([i & 0xff for i in range(256)]))  # settings[i]=i
    emu.wbytes(RX, bytes(0x100))
    emu.uc.mem_write(RX+0, bytes([0x01, cls & 0xff]))            # addr, class
    emu.wbytes(FRAME, bytes([0xEE]*0x80))
    emu.watch=(FRAME, FRAME+0x80)
    emu.call(BUILDER, (0, RX, length))
    return sorted(set((a-FRAME, v) for (pc,a,sz,v) in emu.mem_writes))

classes = [int(x,0) for x in sys.argv[1:]] or [3,4]
for cls in classes:
    ws=probe(cls)
    print("class 0x%02x: %d frame writes" % (cls, len(ws)))
    for off,v in ws:
        tag=" <- settings+0x%02x?"%v if v<0x100 else ""
        print("   frame+0x%02x = 0x%02x%s" % (off, v, tag if off>=2 else ""))
    print()
