#!/usr/bin/env python3
"""
String cross-referencer + symbol renamer for the ARM 'com' firmware.

This firmware materializes addresses with MOVW/MOVT immediate pairs (and ADR /
PC-relative LDR), so string references never appear as data words. This pass
reconstructs those constants per function and records which strings each
function builds -> then proposes names like fn_<string>.

Inputs : FIRMWARE.bin, reference/symbols.csv (from recurse.py)
Outputs: reference/func_string_xref.csv   (func -> strings it references)
         reference/symbols_named.csv       (addr,name  improved)
         reference/ghidra_rename.py         (apply names in Ghidra)
Read-only on the firmware; nothing is executed.
Usage: python3 xref.py FIRMWARE.bin --ref ../reference
"""
import os, struct, argparse, csv, re, bisect, collections
from capstone import *
from capstone.arm import ARM_OP_IMM, ARM_OP_REG, ARM_OP_MEM, ARM_REG_PC

ap = argparse.ArgumentParser()
ap.add_argument("fw"); ap.add_argument("--base", default="0x08000000")
ap.add_argument("--ref", default="../reference")
ap.add_argument("--name-max-strings", type=int, default=3,
                help="only name a function if it refs <= this many distinct strings")
args = ap.parse_args()

BASE = int(args.base, 0)
data = open(args.fw, "rb").read(); N = len(data); END = BASE + N
def rd32(a):
    o=a-BASE; return struct.unpack_from("<I",data,o)[0] if 0<=o<=N-4 else None
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True

# ---- string table (addr -> text), with interval lookup ----------------------
starts=[]; texts={}; ends={}
i=0
while i<N:
    if 32<=data[i]<127:
        j=i
        while j<N and 32<=data[j]<127: j+=1
        if j-i>=4:
            a=BASE+i; starts.append(a); texts[a]=data[i:j].decode("ascii","replace"); ends[a]=BASE+j
        i=j
    else:
        i+=1
starts.sort()
def string_at(v):
    if v is None: return None
    k=bisect.bisect_right(starts, v)-1
    if k>=0 and starts[k]<=v<ends[starts[k]]:
        return starts[k]
    return None

# ---- function entries -------------------------------------------------------
entries={}
with open(os.path.join(args.ref,"symbols.csv")) as f:
    for row in csv.DictReader(f):
        entries[int(row["addr"],16)]=row["name"]
E=sorted(entries)

# ---- per-function constant reconstruction -----------------------------------
func_strs=collections.defaultdict(set)   # entry -> {str_addr}
for idx,entry in enumerate(E):
    end = E[idx+1] if idx+1<len(E) else END
    end = min(end, entry+0x2000)         # cap pathological ranges
    o=entry-BASE
    reg={}
    for ins in md.disasm(data[o:o+(end-entry)], entry):
        mn=ins.mnemonic; ops=ins.operands
        if mn=="movw" and len(ops)==2 and ops[0].type==ARM_OP_REG and ops[1].type==ARM_OP_IMM:
            reg[ops[0].reg]=ops[1].imm & 0xFFFF
        elif mn=="movt" and len(ops)==2 and ops[0].type==ARM_OP_REG and ops[1].type==ARM_OP_IMM:
            r=ops[0].reg; reg[r]=(reg.get(r,0)&0xFFFF)|((ops[1].imm&0xFFFF)<<16)
            sa=string_at(reg[r])
            if sa is not None: func_strs[entry].add(sa)
        elif mn in ("adr","add") and len(ops)>=2 and ops[0].type==ARM_OP_REG:
            # add rX, pc, #imm  (ADR)
            if len(ops)==3 and ops[1].type==ARM_OP_REG and ops[1].reg==ARM_REG_PC and ops[2].type==ARM_OP_IMM:
                v=((ins.address+4)&~3)+ops[2].imm; reg[ops[0].reg]=v
                sa=string_at(v)
                if sa is not None: func_strs[entry].add(sa)
        else:
            # ldr rX,[pc,#imm] literal load
            for op in ops:
                if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
                    la=((ins.address+4)&~3)+op.mem.disp; v=rd32(la)
                    if op.type==ARM_OP_MEM and ops and ops[0].type==ARM_OP_REG:
                        reg[ops[0].reg]=v if v is not None else reg.get(ops[0].reg)
                    sa=string_at(v)
                    if sa is not None: func_strs[entry].add(sa)

# ---- curated, high-confidence names (from disassembly analysis, not guesses) -
CURATED={
    0x0800231c:"SystemInit",        # textbook CMSIS-F1 clock bring-up
    0x080023ee:"SetSysClock",        # called by SystemInit (HSE+PLL->72MHz)
    0x08002938:"__scatterload",      # Keil C-library startup
    0x08002980:"Reset_Handler",      # vector[1]
    0x08002990:"__main",             # entry reached from Reset
    0x080029a8:"Default_Handler",    # shared b.w . trap used by 58 vectors
    0x080018a4:"SysTick_Handler",    # vector[15] (0x...a5)
    0x08002898:"USART3_IRQHandler",  # vector IRQ39
    0x080028a0:"PVD_IRQHandler",     # vector IRQ1
}

def ident(s):
    s=re.sub(r'[^A-Za-z0-9]+','_',s.strip()).strip('_')
    return s[:36]
def nameable(txt):
    """accept only clean human text, reject disassembly noise and SN templates."""
    if txt.startswith("SNEC"): return False
    letters=sum(c.isalpha() for c in txt)
    if letters < 3: return False
    if letters/len(txt) < 0.6: return False            # punctuation-heavy = code noise
    if not re.search(r'[A-Za-z]{4}', txt): return False   # real words; rejects code noise
    if not (any(c.islower() for c in txt) or ' ' in txt):  # font junk is all-caps, no space
        return False
    return True

# drop recurse.py's unreliable auto fn_ names; keep vector/handler names as-is
names={}
for a,nm in entries.items():
    names[a] = f"sub_{a:08x}" if nm.startswith("fn_") else nm
for a,nm in CURATED.items():
    if a in names: names[a]=nm
# strings used by exactly one function are the strongest naming signal
str_user=collections.defaultdict(set)
for fe,sset in func_strs.items():
    for sa in sset: str_user[sa].add(fe)

named=0
for fe in E:
    if not names.get(fe,"").startswith("sub_"): continue   # keep vector/known names
    ss=func_strs.get(fe,set())
    if not ss or len(ss)>args.name_max_strings: continue
    # prefer a string that only this function uses, else the wordiest
    cand=sorted(ss, key=lambda sa:(len(str_user[sa]),
                                   -sum(c.isalpha() for c in texts[sa]), len(texts[sa])))
    for sa in cand:
        if not nameable(texts[sa]): continue
        nm=ident(texts[sa])
        if len(nm)>=3:
            names[fe]="fn_"+nm; named+=1; break

# ---- outputs ----------------------------------------------------------------
with open(os.path.join(args.ref,"func_string_xref.csv"),"w") as fo:
    fo.write("func_addr,proposed_name,n_strings,strings\n")
    for fe in E:
        ss=func_strs.get(fe,set())
        if not ss: continue
        txt=" | ".join(texts[sa].replace(","," ") for sa in sorted(ss))
        fo.write(f"0x{fe:08x},{names.get(fe,'')},{len(ss)},{txt}\n")

with open(os.path.join(args.ref,"symbols_named.csv"),"w") as fo:
    fo.write("addr,name\n")
    for fe in E: fo.write(f"0x{fe:08x},{names.get(fe,f'sub_{fe:08x}')}\n")

with open(os.path.join(args.ref,"ghidra_rename.py"),"w") as fo:
    fo.write("# Ghidra: apply recovered names. Run in Script Manager after import at base 0x08000000.\n")
    fo.write("fm=currentProgram.getFunctionManager()\n")
    fo.write("af=currentProgram.getAddressFactory().getDefaultAddressSpace()\n")
    fo.write("names=[\n")
    for fe in E:
        nm=names.get(fe,f"sub_{fe:08x}")
        if nm.startswith("fn_") or not nm.startswith("sub_"):
            fo.write(f"  (0x{fe:08x},{nm!r}),\n")
    fo.write("]\n")
    fo.write("from ghidra.program.model.symbol import SourceType\n")
    fo.write("for a,n in names:\n")
    fo.write("    addr=af.getAddress(a); f=fm.getFunctionAt(addr)\n")
    fo.write("    if f is None: f=createFunction(addr,n)\n")
    fo.write("    if f is not None: f.setName(n,SourceType.USER_DEFINED)\n")

refd=sum(1 for fe in E if func_strs.get(fe))
print(f"functions total          : {len(E)}")
print(f"functions referencing str: {refd}  (via MOVW/MOVT/ADR/literal)")
print(f"string refs recorded     : {sum(len(s) for s in func_strs.values())}")
print(f"functions newly named    : {named}")
print(f"written to               : {os.path.abspath(args.ref)}")
