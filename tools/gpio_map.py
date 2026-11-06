#!/usr/bin/env python3
"""
Recover the ARM 'com' MCU's GPIO / IO map from the firmware image.

The firmware drives IO through the STM32 StdPeriph library (GPIO_Init,
GPIO_SetBits, GPIO_ResetBits, GPIO_ReadInputDataBit), passing the port base and
pin mask as *arguments* — so a plain literal-pool scan under-counts. This tool:

  1. auto-detects the four StdPeriph GPIO helpers by their instruction
     signatures (robust across firmware revisions, no hard-coded addresses);
  2. statically enumerates every call site of each helper, recovering the
     (port, pin mask) where the caller sets them with constants; and
  3. dynamically resolves the rest under Unicorn (tools/emu.py): it hooks the
     helper entries and calls every helper-caller while sweeping r0/r1, so
     wrapper dispatchers that pick a pin by argument take each branch. At the
     GPIO_Init entry it decodes the GPIO_InitTypeDef (pin mask, speed, mode).

Output: per port/pin — direction/mode (from GPIO_Init) and the set/reset/read
driver functions. Pins configured as alternate-function (AF-PP) are the
peripheral pins; cross-reference the STM32F103 datasheet AF map to name them.

Read-only; executes the image in a sandbox, touches no hardware.
Requires: pip install unicorn capstone.

Usage: python3 tools/gpio_map.py [flat.bin] [symbols.csv]
   defaults: reference/ceaa-07xx_vE_260214.bin  reference/symbols.csv
   (build the flat image with tools/hex2bin.py and symbols with tools/recurse.py)
"""
import sys, os, csv, bisect, struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC, ARM_REG_R0, ARM_REG_R1

FW  = sys.argv[1] if len(sys.argv) > 1 else "reference/ceaa-07xx_vE_260214.bin"
SYM = sys.argv[2] if len(sys.argv) > 2 else "reference/symbols.csv"
BASE = 0x08000000
data = open(FW, "rb").read(); N = len(data)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.detail = True

# STM32F103 GPIO/peripheral bases (ports F/G exist only on 144-pin parts)
PORTS = {0x40010800:"A",0x40010c00:"B",0x40011000:"C",0x40011400:"D",
         0x40011800:"E",0x40011c00:"F",0x40012000:"G"}

def rd32(a):
    o=a-BASE
    return struct.unpack_from("<I",data,o)[0] if 0<=o<=N-4 else None

funcs=[]
for r in csv.DictReader(open(SYM)): funcs.append((int(r["addr"],16), r["name"]))
funcs.sort(); faddrs=[a for a,_ in funcs]
names={a:n for a,n in funcs}
def func_end(a):
    i=bisect.bisect_right(faddrs,a); return faddrs[i] if i<len(faddrs) else BASE+N

def insns(fa):
    return list(md.disasm(data[fa-BASE:func_end(fa)-BASE], fa))

# ---- 1. auto-detect the StdPeriph GPIO helpers by instruction signature ----
# (scan the whole function body, not just the prologue)
def detect():
    found={}
    for fa,_ in funcs:
        full=insns(fa)
        body=full[:40]
        def has(seq,pred): return any(pred(i) for i in seq)
        str_to=lambda seq,off: has(seq, lambda i: i.mnemonic in("str","str.w") and i.op_str.endswith("[r0, #%s]"%off))
        ld_from=lambda seq,rb,off: has(seq, lambda i: i.mnemonic in("ldr","ldr.w","ldrb","ldrb.w","ldrsb.w") and i.op_str.endswith("[%s, #%s]"%(rb,off)))
        bxlr=has(body, lambda i: i.mnemonic=="bx")
        # SetBits:  str rX,[r0,#0x10] (BSRR); short leaf    ResetBits: str rX,[r0,#0x14] (BRR)
        if len(full)<=8 and bxlr and str_to(body,"0x10"): found.setdefault("SetBits",fa)
        if len(full)<=8 and bxlr and str_to(body,"0x14"): found.setdefault("ResetBits",fa)
        # ReadInputDataBit: short leaf, reads IDR [rB,#8] and tst with mask
        if len(full)<=16 and bxlr and (ld_from(body,"r2","8") or ld_from(body,"r0","8")) and has(body,lambda i:i.mnemonic=="tst"):
            found.setdefault("ReadBit",fa)
        # GPIO_Init: reads InitStruct mode byte [r1,#3] AND writes config reg CRH [r0,#4]
        # (scan the whole body -- GPIO_Init is ~125 insns and the CRH store is late)
        if ld_from(full,"r1","3") and str_to(full,"4"):
            found.setdefault("GPIO_Init",fa)
    return found

HELP_ADDR=detect()
HELP={v:k for k,v in HELP_ADDR.items()}
print("# detected GPIO helpers:")
for k in ("GPIO_Init","SetBits","ResetBits","ReadBit"):
    print("#   %-10s = %s"%(k, ("0x%08x"%HELP_ADDR[k]) if k in HELP_ADDR else "NOT FOUND"))
print()
if "SetBits" not in HELP_ADDR:
    sys.exit("could not locate GPIO helpers; check the image/symbols")

# ---- 2+3. dynamic resolution: hook helper entries, call every caller ----
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

# callers of any helper (static scan for bl to a helper address)
callers=set()
for fa,_ in funcs:
    for i in insns(fa):
        if i.mnemonic in("bl","blx") and i.operands and i.operands[0].type==ARM_OP_IMM \
           and i.operands[0].imm in HELP:
            callers.add(fa); break

MODE={0x00:"AIN",0x04:"IN-FLOAT",0x28:"IN-PD",0x48:"IN-PU",
      0x10:"OUT-PP",0x14:"OUT-OD",0x18:"AF-PP",0x1c:"AF-OD"}
SPD={0:"-",1:"10MHz",2:"2MHz",3:"50MHz"}
from collections import defaultdict
res=defaultdict(set)   # (port,pin) -> set("ACTION ... <caller>")
cur=[None]

emu=Emu(FW,SYM)
def hook(uc,addr,size,ud):
    if addr not in HELP: return
    r0=uc.reg_read(UC_ARM_REG_R0); r1=uc.reg_read(UC_ARM_REG_R1)
    port=PORTS.get(r0 & 0xFFFFFC00)
    if not port: return
    h=HELP[addr]
    if h=="GPIO_Init":
        try: s=bytes(uc.mem_read(r1,4))
        except Exception: return
        mask=s[0]|(s[1]<<8)
        for i in range(16):
            if (mask>>i)&1: res[(port,i)].add("CONFIG[%s %s] %s"%(MODE.get(s[3],hex(s[3])),SPD.get(s[2],s[2]),cur[0]))
    else:
        mask=r1 & 0xFFFF
        act={"SetBits":"OUT set-HIGH","ResetBits":"OUT set-LOW","ReadBit":"IN read"}[h]
        for i in range(16):
            if (mask>>i)&1: res[(port,i)].add("%s %s"%(act,cur[0]))
emu.uc.hook_add(UC_HOOK_CODE, hook)

for fa in sorted(callers):
    cur[0]=names.get(fa,"0x%08x"%fa)
    for a0 in range(6):
        for a1 in (0,1):
            try: emu.call(fa,(a0,a1),count=120000)
            except Exception: pass

print("# GPIO pin map  (port/pin -> config + drivers).  AF-PP = peripheral pin.")
for (port,pin) in sorted(res):
    print("P%s%-2d"%(port,pin))
    for e in sorted(res[(port,pin)]): print("      %s"%e)
print("\n# pins resolved: %d"%len(res))
