#!/usr/bin/env python3
"""
Disassemble a Thumb function with light constant-tracking, resolving
pc-relative literal loads and (base+offset) memory targets to absolute
addresses. Invaluable for reading which RAM fields a function touches.

For each instruction it annotates:
  ; =0x........   the value loaded from a pc-relative literal pool
  ; @0x........   the absolute target of a load/store whose base register
                  currently holds a known literal (RAM/peripheral field)
  -> name         the callee of a bl/blx (from symbols.csv)

Read-only static analysis. Requires: pip install capstone.

Usage: python3 tools/disres.py ADDR [ADDR...] [--img F] [--sym F]
   ADDR is a hex function address (0x........).
   defaults: --img reference/ceaa-07xx_vE_260214.bin  --sym reference/symbols.csv
"""
import sys, struct, csv, bisect, argparse
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

ap = argparse.ArgumentParser()
ap.add_argument("addrs", nargs="+", help="hex function addresses")
ap.add_argument("--img", default="reference/ceaa-07xx_vE_260214.bin")
ap.add_argument("--sym", default="reference/symbols.csv")
ap.add_argument("--base", default="0x08000000")
args = ap.parse_args()

BASE = int(args.base, 0)
d = open(args.img, "rb").read()
names = {int(r["addr"], 16): r["name"] for r in csv.DictReader(open(args.sym))}
fa = sorted(names)
def end(a):
    i = bisect.bisect_right(fa, a); return fa[i] if i < len(fa) else BASE + len(d)
def rd32(a):
    o = a - BASE; return struct.unpack_from("<I", d, o)[0] if 0 <= o <= len(d)-4 else None
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True

def dis(a):
    print("=== %s (0x%08x) ===" % (names.get(a, hex(a)), a))
    reg = {}
    for ins in md.disasm(d[a-BASE:end(a)-BASE], a):
        m, ops, ann = ins.mnemonic, ins.operands, ""
        if m in ("ldr","ldr.w") and len(ops)==2 and ops[1].type==ARM_OP_MEM and ops[1].mem.base==ARM_REG_PC:
            pc=(ins.address+4)&~3; lit=rd32(pc+ops[1].mem.disp)
            if lit is not None: reg[ops[0].reg]=lit; ann=" ; =0x%08x"%lit
        elif m in ("movs","mov","mov.w") and len(ops)==2 and ops[1].type==ARM_OP_IMM:
            reg[ops[0].reg]=ops[1].imm & 0xFFFFFFFF
        elif m=="movt" and len(ops)==2 and ops[1].type==ARM_OP_IMM:
            reg[ops[0].reg]=(reg.get(ops[0].reg,0)&0xFFFF)|((ops[1].imm&0xFFFF)<<16)
        if ops and ops[-1].type==ARM_OP_MEM and ops[-1].mem.base!=ARM_REG_PC:
            b=reg.get(ops[-1].mem.base)
            if b is not None and 0x20000000<=b<0x20010000:
                ann=" ; @0x%08x"%(b+ops[-1].mem.disp)
        if m in ("bl","blx") and ops and ops[0].type==ARM_OP_IMM:
            ann=" -> %s"%names.get(ops[0].imm, hex(ops[0].imm))
        if ops and ops[0].type==ARM_OP_REG and m not in ("str","strh","strb","cmp","cmn","tst","teq","ldr","movs","mov","mov.w","movt"):
            reg.pop(ops[0].reg, None)
        if m in ("bl","blx"):
            for rr in (0,1,2,3): reg.pop(rr, None)
        print("  0x%08x %-8s %s%s" % (ins.address, m, ins.op_str, ann))
    print()

for a in args.addrs:
    dis(int(a, 16))
