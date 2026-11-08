#!/usr/bin/env python3
"""
Segment an ARM image's static RAM by the base pointers its code loads.

For every function (symbols.csv), it tracks constant registers built from
MOVW/MOVT, PC-relative LDR literals, and ADD/SUB-immediate chains (like
tools/ramxref.py), and ties each memory access back to the base *literal* it
came from. Consecutive base literals partition the static RAM block into
objects; the gap to the next base bounds each object's size, and the max offset
seen through a base is a lower bound. Large literal-free gaps are big buffers
reached only via indexed/computed pointers (size them with a loop bound or a
memset/memcpy length — see tools/ramxref.py and the RB-S notes in docs/47).

This is the tool behind the RB-S1 static breakdown in docs/46 / docs/47.
Read-only; nothing is executed. Requires: pip install capstone.

Usage: python3 tools/ramsegments.py [--img F] [--sym F] [--lo 0x.. --hi 0x..]
  defaults: img reference/ceaa-07xx_vE_260214.bin, sym reference/symbols.csv,
            static block 0x20000000..0x2000dbd8 (the ceaa-07xx .bss+.data top).
"""
import struct, csv, argparse
from collections import defaultdict
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

ap = argparse.ArgumentParser()
ap.add_argument("--img", default="reference/ceaa-07xx_vE_260214.bin")
ap.add_argument("--sym", default="reference/symbols.csv")
ap.add_argument("--base", default="0x08000000")
ap.add_argument("--lo", default="0x20000000")
ap.add_argument("--hi", default="0x2000dbd8")
args = ap.parse_args()

BASE = int(args.base, 0); RLO = int(args.lo, 0); RHI = int(args.hi, 0)
RAM_LO, RAM_HI = 0x20000000, 0x20010000
data = open(args.img, "rb").read(); N = len(data); END = BASE + N
def rd32(a):
    o = a - BASE; return struct.unpack_from("<I", data, o)[0] if 0 <= o <= N - 4 else None

ent = {int(r["addr"], 16): r["name"] for r in csv.DictReader(open(args.sym))}
E = sorted(ent)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True
STORES = {"str", "strh", "strb", "strd"}; LOADS = {"ldr", "ldrh", "ldrb", "ldrsh", "ldrsb", "ldrd"}
ESZ = {"strb": 1, "ldrb": 1, "ldrsb": 1, "strh": 2, "ldrh": 2, "ldrsh": 2, "str": 4, "ldr": 4, "strd": 8, "ldrd": 8}

seg = defaultdict(lambda: {"n": 0, "maxoff": 0, "funcs": set(), "idx": set()})
baserefs = defaultdict(set)   # literal -> funcs that load it (even if never dereffed)

for i, fs in enumerate(E):
    fe = E[i + 1] if i + 1 < len(E) else END
    reg = {}   # r -> (origin_literal_or_None, value)
    def note_base(v):
        if RAM_LO <= v < RAM_HI: baserefs[v].add(ent[fs])
    for ins in md.disasm(data[fs - BASE:fe - BASE], fs):
        m = ins.mnemonic; bm = m.split(".")[0]; ops = ins.operands
        if m == "movw" and ops[1].type == ARM_OP_IMM:
            reg[ops[0].reg] = (None, ops[1].imm & 0xffff)
        elif m == "movt" and ops[1].type == ARM_OP_IMM:
            r = ops[0].reg; v = (reg.get(r, (None, 0))[1] & 0xffff) | ((ops[1].imm & 0xffff) << 16)
            reg[r] = (v, v) if RAM_LO <= v < RAM_HI else (None, v); note_base(v)
        elif m in ("mov", "movs") and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            reg[ops[0].reg] = (None, ops[1].imm)
        elif m in ("mov", "movs") and len(ops) == 2 and ops[1].type == ARM_OP_REG and ops[1].reg in reg:
            reg[ops[0].reg] = reg[ops[1].reg]
        elif bm == "ldr" and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
            v = rd32(((ins.address + 4) & ~3) + ops[1].mem.disp)
            if v is not None:
                reg[ops[0].reg] = (v, v) if RAM_LO <= v < RAM_HI else (None, v); note_base(v)
            else:
                reg.pop(ops[0].reg, None)
        elif bm in ("add", "addw", "adds") and len(ops) == 3 and ops[2].type == ARM_OP_IMM and ops[1].type == ARM_OP_REG and ops[1].reg in reg:
            o, v = reg[ops[1].reg]; reg[ops[0].reg] = (o, (v + ops[2].imm) & 0xffffffff)
        elif bm in ("sub", "subw", "subs") and len(ops) == 3 and ops[2].type == ARM_OP_IMM and ops[1].type == ARM_OP_REG and ops[1].reg in reg:
            o, v = reg[ops[1].reg]; reg[ops[0].reg] = (o, (v - ops[2].imm) & 0xffffffff)
        elif (bm in STORES or bm in LOADS) and len(ops) >= 2 and ops[-1].type == ARM_OP_MEM:
            mem = ops[-1].mem
            if mem.base in reg:
                o, v = reg[mem.base]; origin = o if o is not None else (v if RAM_LO <= v < RAM_HI else None)
                if origin is not None and RLO <= origin < RHI:
                    s = seg[origin]; s["n"] += 1; s["funcs"].add(ent[fs])
                    s["maxoff"] = max(s["maxoff"], (v + mem.disp - origin) + ESZ.get(bm, 4))
                    if mem.index != 0: s["idx"].add((1 << mem.lshift) if mem.lshift else ESZ.get(bm, 4))
            if bm in LOADS and ops[0].type == ARM_OP_REG and ops[0].reg != mem.base: reg.pop(ops[0].reg, None)
        elif ops and ops[0].type == ARM_OP_REG and bm not in ("cmp", "cmn", "tst", "teq"):
            reg.pop(ops[0].reg, None)

bases = sorted(set(seg) | {b for b in baserefs if RLO <= b < RHI})
objs = [(bases[i + 1] if i + 1 < len(bases) else RHI) - b for i, b in enumerate(bases)]
print("# %s  static block 0x%08x..0x%08x : %d base literals, %d B" % (args.img, RLO, RHI, len(bases), sum(objs)))
print("\n### size distribution (objects = consecutive base literals) ###")
for lo_, hi_, lab in [(0, 64, "<64B"), (64, 256, "64-256B"), (256, 1024, "256B-1KB"), (1024, 4096, "1-4KB"), (4096, 1 << 20, ">=4KB")]:
    sel = [s for s in objs if lo_ <= s < hi_]
    print("  %-10s : %3d objects, %6d B (%.1f KB)" % (lab, len(sel), sum(sel), sum(sel) / 1024))

print("\n### objects >= 512 B (the bulk) ###")
rows = sorted(((objs[i], b) for i, b in enumerate(bases)), reverse=True)
for size, b in rows:
    if size < 512: break
    s = seg.get(b); mo = s["maxoff"] if s else 0; refs = (s["n"] if s else 0)
    arr = "arr%s" % sorted(s["idx"]) if (s and s["idx"]) else ""
    ld = sorted(baserefs.get(b, set()))[:2]
    print("  0x%08x  %6d B (%.1f KB)  refs=%4d maxoff=%5d %-8s  %s" % (b, size, size / 1024, refs, mo, arr, ",".join(ld)))
