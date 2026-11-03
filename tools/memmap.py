import sys, struct
from capstone import *
path=sys.argv[1]; data=open(path,'rb').read()
FLASH=0x08000000; n=len(data)
def rd32(o): return struct.unpack_from('<I',data,o)[0]
md=Cs(CS_ARCH_ARM,CS_MODE_THUMB); md.detail=True

# reset literals
L1=rd32(0x2988); L2=rd32(0x298c)
print(f"Reset: calls 0x{L1:08x} (SystemInit?), then jumps 0x{L2:08x} (startup/_start)")
print(f"image spans 0x{FLASH:08x} .. 0x{FLASH+n:08x}  (used {n} = 0x{n:x} bytes)\n")

def show(addr, cnt, title):
    print(f"=== {title} @ 0x{addr:08x} ===")
    o=addr-FLASH
    for ins in md.disasm(data[o:o+cnt*4], addr):
        cnt-=1
        print(f"  0x{ins.address:08x}  {ins.bytes.hex():10} {ins.mnemonic:8} {ins.op_str}")
        if cnt<=0: break

for a,t in [(L1&~1,"SystemInit"),(L2&~1,"startup")]:
    show(a,48,t); print()

# find 32-bit words pointing into RAM (0x20000000) in the startup region to spot data/bss symbols
print("=== RAM-pointing words near startup (candidate _sdata/_edata/_sbss/_ebss) ===")
start=(L2&~1)-FLASH
for o in range(start, min(start+0x200,n-4),4):
    v=rd32(o)
    if 0x20000000<=v<0x20020000:
        print(f"  flash 0x{FLASH+o:08x} -> RAM 0x{v:08x}")
