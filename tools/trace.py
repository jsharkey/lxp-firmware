import sys, struct, collections
from capstone import *
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

path=sys.argv[1]; data=open(path,'rb').read()
FLASH=0x08000000; n=len(data)
def rd32(o): return struct.unpack_from('<I',data,o)[0]
def off(addr): return addr-FLASH
md=Cs(CS_ARCH_ARM,CS_MODE_THUMB); md.detail=True

def disasm(start_addr, count):
    o=off(start_addr); out=[]
    for ins in md.disasm(data[o:o+count*4], start_addr):
        out.append(ins)
        if len(out)>=count: break
    return out

print("=== Reset_Handler @ 0x08002980 ===")
for ins in disasm(0x08002980, 40):
    print(f"  0x{ins.address:08x}  {ins.mnemonic:8} {ins.op_str}")

# proper PC-relative literal pool extraction
print("\n=== genuine peripheral literals (PC-rel LDR, 0x4000_0000-0x5000_0000) ===")
peri=collections.Counter()
for ins in md.disasm(data, FLASH):
    if ins.id==0: continue
    for op in ins.operands:
        if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
            # literal address
            pc=(ins.address+4)&~3
            la=pc+op.mem.disp
            if 0<=off(la)<=n-4:
                val=rd32(off(la))
                if 0x40000000<=val<0x50000000:
                    peri[val]+=1
names={0x40021000:"RCC",0x40022000:"FLASH",0x40013800:"USART1",0x40004400:"USART2",
0x40004800:"USART3",0x40004c00:"UART4",0x40005000:"UART5",0x40006400:"CAN1",0x40006800:"CAN2",
0x40010800:"GPIOA",0x40010c00:"GPIOB",0x40011000:"GPIOC",0x40011400:"GPIOD",0x40011800:"GPIOE",
0x40011c00:"GPIOF",0x40012000:"GPIOG",0x40010000:"AFIO",0x40010400:"EXTI",0x40012400:"ADC1",
0x40012800:"ADC2",0x40013c00:"ADC3",0x40012c00:"TIM1",0x40000000:"TIM2",0x40000400:"TIM3",
0x40000800:"TIM4",0x40000c00:"TIM5",0x40001000:"TIM6",0x40001400:"TIM7",0x40013400:"TIM8",
0x40013000:"SPI1",0x40003800:"SPI2",0x40003c00:"SPI3",0x40005400:"I2C1",0x40005800:"I2C2",
0x40020000:"DMA1",0x40020400:"DMA2",0x40002800:"RTC",0x40006c00:"BKP",0x40007000:"PWR",
0x40007400:"DAC",0x40002c00:"WWDG",0x40003000:"IWDG",0x40003c00:"SPI3"}
for v,c in peri.most_common(30):
    # bucket to 1KB block for name
    blk=v & 0xFFFFFC00
    print(f"  0x{v:08x} x{c:<4} {names.get(blk,'')}")
