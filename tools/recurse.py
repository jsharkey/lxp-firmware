#!/usr/bin/env python3
"""
Function mapper for the ARM 'com' firmware (EG4 18kPV-12LV, STM32F103).

This firmware is Keil/armcc-built and calls functions mostly INDIRECTLY via
`ldr rX,[pc,#imm]; blx rX`, so pure call-following stops immediately. We instead
discover functions three ways and merge them:
  (1) vector-table entries,
  (2) odd (thumb) code pointers found in literal pools / function tables,
  (3) `push {...,lr}` prologues (0xB5xx / 0xE92D.w) in gaps.
Then we linearly sweep each function, record call edges and string xrefs, and
name functions by the strings they reference.

Outputs to --out: symbols.csv, strings_xref.csv, callgraph.txt
Read-only; nothing is executed.

Usage: python3 recurse.py FIRMWARE.bin --out ../reference
"""
import sys, os, struct, argparse, collections, re
from capstone import *
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

ap = argparse.ArgumentParser()
ap.add_argument("fw"); ap.add_argument("--base", default="0x08000000")
ap.add_argument("--out", default="."); ap.add_argument("--max-insn", type=int, default=2_000_000)
args = ap.parse_args()

BASE = int(args.base, 0)
data = open(args.fw, "rb").read()
N = len(data); END = BASE + N
os.makedirs(args.out, exist_ok=True)

def rd32(a):
    o = a - BASE
    return struct.unpack_from("<I", data, o)[0] if 0 <= o <= N-4 else None
def rd16(a):
    o = a - BASE
    return struct.unpack_from("<H", data, o)[0] if 0 <= o <= N-2 else None
def in_flash(a): return a is not None and BASE <= a < END

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True

# ---- string table -----------------------------------------------------------
strings = {}
i = 0
while i < N:
    if 32 <= data[i] < 127:
        j = i
        while j < N and 32 <= data[j] < 127: j += 1
        if j - i >= 4: strings[BASE+i] = data[i:j].decode("ascii","replace")
        i = j
    else:
        i += 1
str_starts = set(strings)

def looks_like_prologue(a):
    hw = rd16(a)
    if hw is None: return False
    if (hw & 0xFF00) == 0xB500: return True          # push {..., lr} (16-bit)
    if hw == 0xE92D: return True                      # push.w {...} (stmdb sp!)
    return False

# ---- seeds ------------------------------------------------------------------
seeds = {}
def seed(a, name):
    a &= ~1
    if in_flash(a): seeds.setdefault(a, name)

VEC_SYS = [None,"Reset","NMI","HardFault","MemManage","BusFault","UsageFault",
           None,None,None,None,"SVCall","DebugMon",None,"PendSV","SysTick"]
for k in range(1,16):
    v = rd32(BASE+k*4)
    if v and VEC_SYS[k]: seed(v, VEC_SYS[k]+"_Handler")
VEC_IRQ = {1:"PVD_Handler", 39:"USART3_Handler"}
for k in range(60):
    v = rd32(BASE+(16+k)*4)
    if v: seed(v, VEC_IRQ.get(k, f"IRQ{k}_Handler"))

# ---- discovery + sweep ------------------------------------------------------
funcs = {}                                   # entry -> {'n':insns,'end':addr}
calls = collections.defaultdict(set)
xrefs = collections.defaultdict(set)
insn_starts = set()
budget = args.max_insn
work = collections.deque(seeds)
queued = set(seeds)

def sweep(entry):
    global budget
    local_seen = set()
    pending = [entry]
    end = entry
    ninsns = 0
    while pending:
        pc = pending.pop()
        o = pc - BASE
        if o < 0 or o >= N: continue
        for ins in md.disasm(data[o:], pc):
            if budget <= 0: break
            if ins.address in local_seen: break
            local_seen.add(ins.address); insn_starts.add(ins.address)
            budget -= 1; ninsns += 1
            end = max(end, ins.address + ins.size)
            mn = ins.mnemonic; g = set(ins.groups)

            for op in ins.operands:
                if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                    la = ((ins.address + 4) & ~3) + op.mem.disp
                    v = rd32(la)
                    if v is None: continue
                    if v in str_starts:                       # string pointer
                        xrefs[v].add(entry)
                    elif (v & 1) and in_flash(v & ~1):        # thumb code pointer
                        t = v & ~1
                        if t not in queued:
                            queued.add(t); work.append(t)
                        calls[entry].add(t)

            if CS_GRP_CALL in g:                               # bl/blx imm
                for op in ins.operands:
                    if op.type == ARM_OP_IMM and in_flash(op.imm & ~1):
                        t = op.imm & ~1
                        calls[entry].add(t)
                        if t not in queued: queued.add(t); work.append(t)
                continue
            if CS_GRP_RET in g: break
            if mn.startswith("pop") and "pc" in ins.op_str: break
            if mn == "bx": break
            if CS_GRP_JUMP in g:
                tgt = next((op.imm & ~1 for op in ins.operands if op.type==ARM_OP_IMM), None)
                is_uncond = mn in ("b","b.w")
                if tgt is not None and in_flash(tgt):
                    if entry <= tgt <= end + 0x600 or not is_uncond:
                        pending.append(tgt)                    # intra-function
                    else:                                      # tail call
                        calls[entry].add(tgt)
                        if tgt not in queued: queued.add(tgt); work.append(tgt)
                if is_uncond: break
                else: continue
        if budget <= 0: break
    return ninsns, end

def run_queue():
    while work and budget > 0:
        e = work.popleft()
        if e in funcs: continue
        n, end = sweep(e)
        funcs[e] = {"n": n, "end": end}

run_queue()
# prologue fallback: find push{lr} prologues in gaps, add & re-run
added = 0
for a in range(BASE, END, 2):
    if a in funcs or a in insn_starts: continue
    if looks_like_prologue(a):
        if a not in queued:
            queued.add(a); work.append(a); added += 1
run_queue()

# ---- naming -----------------------------------------------------------------
def ident(s):
    s = re.sub(r'[^A-Za-z0-9]+','_',s.strip()).strip('_')
    return s[:40]
names = dict(seeds)
f2s = collections.defaultdict(list)
for sa, fs in xrefs.items():
    for f in fs: f2s[f].append(strings[sa])
for f, sl in f2s.items():
    if f in names: continue
    for c in sorted(set(sl), key=lambda t:(-sum(ch.isalpha() for ch in t), len(t))):
        nm = ident(c)
        if len(nm) >= 3 and any(ch.isalpha() for ch in nm):
            names[f] = "fn_"+nm; break

# ---- outputs ----------------------------------------------------------------
with open(os.path.join(args.out,"symbols.csv"),"w") as fo:
    fo.write("addr,kind,name,insns,notes\n")
    for a in sorted(funcs):
        fo.write(f"0x{a:08x},func,{names.get(a, f'sub_{a:08x}')},{funcs[a]['n']},"
                 f"{'vector' if a in seeds else ''}\n")
with open(os.path.join(args.out,"strings_xref.csv"),"w") as fo:
    fo.write("str_addr,n_refs,referenced_by,text\n")
    for sa in sorted(xrefs):
        refs=" ".join(f"0x{f:08x}" for f in sorted(xrefs[sa]))
        fo.write(f"0x{sa:08x},{len(xrefs[sa])},{refs},{strings[sa].replace(chr(10),' ')}\n")
with open(os.path.join(args.out,"callgraph.txt"),"w") as fo:
    for c in sorted(calls):
        for e in sorted(calls[c]):
            fo.write(f"{names.get(c,f'sub_{c:08x}')} -> {names.get(e,f'sub_{e:08x}')}\n")

named = sum(1 for a in funcs if a in names)
tot = sum(f["n"] for f in funcs.values())
print(f"strings            : {len(strings)}")
print(f"functions          : {len(funcs)}  (+{added} from prologue scan)")
print(f"  named via strings: {named} ({named*100//max(len(funcs),1)}%)")
print(f"string xrefs       : {len(xrefs)} strings referenced by code")
print(f"call edges         : {sum(len(v) for v in calls.values())}")
print(f"reachable insns    : {tot}  (~{tot*2} bytes = {tot*2*100//N}% of image is code)")
print(f"budget left        : {budget}")
print(f"written to         : {os.path.abspath(args.out)}")
