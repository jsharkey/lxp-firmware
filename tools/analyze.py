import sys, struct, math, collections

path = sys.argv[1]
data = open(path,'rb').read()
FLASH_BASE = 0x08000000
RAM_BASE   = 0x20000000
n = len(data)
print(f"size = {n} bytes ({n/1024:.1f} KiB)")

# --- entropy in 2KB blocks ---
def ent(b):
    if not b: return 0.0
    c = collections.Counter(b); L=len(b)
    return -sum((v/L)*math.log2(v/L) for v in c.values())
print("\n=== entropy map (2KB blocks, flag >7.5 = possible crypt/compress) ===")
BS=2048; flagged=0
for i in range(0, n, BS):
    e = ent(data[i:i+BS])
    bar = "#"*int(e*4)
    flag = "  <== HIGH" if e>7.5 else ""
    if i % (BS*8)==0 or e>7.5:
        print(f"  0x{FLASH_BASE+i:08x}  {e:4.2f} {bar}{flag}")
    if e>7.5: flagged+=1
print(f"overall entropy = {ent(data):.3f} ; high-entropy blocks = {flagged}")

# --- vector table ---
print("\n=== vector table ===")
sp = struct.unpack_from('<I', data, 0)[0]
print(f"[0] Initial SP      = 0x{sp:08x}  (RAM top)")
names = ["Reset","NMI","HardFault","MemManage","BusFault","UsageFault",
         "RSVD6","RSVD7","RSVD8","RSVD9","SVCall","DebugMon","RSVD12","PendSV","SysTick"]
for i in range(1,16):
    v = struct.unpack_from('<I', data, i*4)[0]
    print(f"[{i:2}] {names[i-1]:10} = 0x{v:08x}")

# Count external IRQ vectors: entries that look like thumb code ptrs (odd, in flash range)
print("\n=== external IRQ vectors (addr in flash & thumb bit set) ===")
irq=[]
i=16
while i*4+4 <= n:
    v = struct.unpack_from('<I', data, i*4)[0]
    if FLASH_BASE <= v < FLASH_BASE+n and (v & 1):
        irq.append((i-16, v))
        i+=1
    else:
        break
print(f"external IRQ count (contiguous) = {len(irq)}  -> last IRQ# {irq[-1][0] if irq else 'n/a'}")
for num,v in irq[:8]+ (["..."] if len(irq)>16 else []) + irq[-4:] if irq else []:
    pass
for num,v in irq:
    print(f"  IRQ{num:3} -> 0x{v:08x}")
