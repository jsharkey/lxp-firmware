import sys, struct
sys.path.insert(0,"tools")
from emu import Emu
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1
emu=Emu("reference/ceaa-07xx_vE_260214.bin","reference/symbols_named.csv")
# seed RAM 0..0xC000 with per-word markers = word index
blob=bytearray()
for w in range(0,0xC000//2): blob+=struct.pack("<H", w & 0xFFFF)
emu.uc.mem_write(0x20000000, bytes(blob))
emu.stubs={0x0801435c:1}   # gate: bit0 set -> TX send path
emu.stop_at={0x0801c370}            # the send-frame call
emu.call(0x08015094, count=4_000_000)
pc=emu.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_PC)
if (pc & ~1)==0x0801c370:
    ptr=emu.uc.reg_read(UC_ARM_REG_R0); ln=emu.uc.reg_read(UC_ARM_REG_R1)&0xFFFF
    print(f"REACHED sub_0801c370(ptr=0x{ptr:08x}, len={ln})")
    data=emu.rbytes(ptr, min(ln if ln else 64, 128))
    print("frame bytes:", " ".join(f"{b:02x}" for b in data))
    if len(data)>=0x16:
        print(f"  addr=0x{data[0]:02x}  type=0x{data[1]:02x}  block_id@0x14=0x{data[0x14]:02x}")
else:
    print(f"did not reach sub_0801c370 (pc=0x{pc:08x})")
