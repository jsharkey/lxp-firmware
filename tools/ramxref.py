#!/usr/bin/env python3
"""
RAM cross-referencer for the ARM 'com' firmware.

Finds which functions read or write a given RAM address (or range), tracking
constant base registers built from MOVW/MOVT pairs, PC-relative LDR literals,
and ADD/SUB-immediate chains (so `ldr r0,=0x20009854; strb r1,[r0,#0x17]` is
attributed to 0x2000986b). This is the tool behind the register->offset and
"does X reach the DSP frame" traces in docs/08.

Note: constant-base only. Stores via register-indexed addressing (str [rB,rIdx])
or memcpy are not resolved -- a function that builds a frame that way shows up as
having no hit, which is itself a signal (see docs/08: the 0x20009414 frame).

Usage:
  python3 tools/ramxref.py 0x2000986b                 # reads+writes of one byte
  python3 tools/ramxref.py 0x20009414 0x20009460 store # writers of a range
  python3 tools/ramxref.py 0x2000a758 0x2000a75c load  # readers of a range
Read-only; nothing is executed.
"""
import sys, os, struct, csv, bisect
from capstone import *
from capstone.arm import *

FW   = os.environ.get("RAMXREF_FW", "reference/com_flat.bin")
BASE = 0x08000000
data = open(FW, "rb").read(); N = len(data); END = BASE + N
def rd32(a):
    o = a - BASE; return struct.unpack_from("<I", data, o)[0] if 0 <= o <= N-4 else None

entries = {}
with open(os.environ.get("RAMXREF_SYMS", "reference/symbols.csv")) as f:
    for row in csv.DictReader(f): entries[int(row["addr"], 16)] = row["name"]
E = sorted(entries)

lo = int(sys.argv[1], 0)
hi = int(sys.argv[2], 0) if len(sys.argv) > 2 and sys.argv[2].startswith("0x") else lo + 1
mode = next((a for a in sys.argv[2:] if a in ("store", "load", "both")), "both")

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True
STORES = {"str", "strh", "strb", "strd"}
LOADS  = {"ldr", "ldrh", "ldrb", "ldrsh", "ldrsb"}
from collections import defaultdict
byf = defaultdict(list)

for idx, fs in enumerate(E):
    fe = E[idx+1] if idx+1 < len(E) else END
    regc = {}
    for ins in md.disasm(data[fs-BASE:fe-BASE], fs):
        m = ins.mnemonic; bm = m.split(".")[0]; ops = ins.operands
        if m == "movw" and ops[1].type == ARM_OP_IMM: regc[ops[0].reg] = ops[1].imm & 0xffff
        elif m == "movt" and ops[1].type == ARM_OP_IMM:
            r = ops[0].reg; regc[r] = (regc.get(r, 0) & 0xffff) | ((ops[1].imm & 0xffff) << 16)
        elif m in ("mov", "movs") and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            regc[ops[0].reg] = ops[1].imm
        elif bm == "ldr" and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
            lit = (ins.address+4) & ~3; v = rd32(lit + ops[1].mem.disp)
            if v is not None: regc[ops[0].reg] = v
            else: regc.pop(ops[0].reg, None)
        elif bm in ("add", "addw", "adds") and len(ops) == 3 and ops[2].type == ARM_OP_IMM and ops[1].type == ARM_OP_REG and ops[1].reg in regc:
            regc[ops[0].reg] = (regc[ops[1].reg] + ops[2].imm) & 0xffffffff
        elif bm in ("sub", "subw", "subs") and len(ops) == 3 and ops[2].type == ARM_OP_IMM and ops[1].type == ARM_OP_REG and ops[1].reg in regc:
            regc[ops[0].reg] = (regc[ops[1].reg] - ops[2].imm) & 0xffffffff
        elif (bm in STORES or bm in LOADS) and len(ops) >= 2 and ops[-1].type == ARM_OP_MEM:
            mem = ops[-1].mem
            if mem.base in regc and mem.index == 0:
                tgt = (regc[mem.base] + mem.disp) & 0xffffffff
                if lo <= tgt < hi:
                    kind = "ST" if bm in STORES else "ld"
                    if mode == "both" or (mode == "store") == (kind == "ST"):
                        byf[(fs, entries[fs])].append((kind, ins.address, tgt, "%s %s" % (m, ins.op_str)))
            if bm in LOADS and ops[0].type == ARM_OP_REG: regc.pop(ops[0].reg, None)
        elif ops and ops[0].type == ARM_OP_REG and bm not in ("cmp", "cmn", "tst", "teq"):
            regc.pop(ops[0].reg, None)

print("# 0x%08x..0x%08x  mode=%s  : %d functions" % (lo, hi, mode, len(byf)))
for (fs, nm), items in sorted(byf.items()):
    print("\n%s (0x%08x):" % (nm, fs))
    for kind, ia, tgt, txt in items:
        print("   %s @0x%08x -> 0x%08x  %s" % (kind, ia, tgt, txt))
