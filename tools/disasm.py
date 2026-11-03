import sys, struct, collections
from capstone import *

path = sys.argv[1]
data = open(path,'rb').read()
FLASH=0x08000000; n=len(data)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

def rd32(off): return struct.unpack_from('<I', data, off)[0]

# default handler cluster
reset = rd32(4) & ~1
print(f"Reset_Handler @ 0x{FLASH+reset:08x}")

# IRQ handlers: which are unique (used) vs shared default
irq_addrs=[]
for i in range(16, 16+60):
    irq_addrs.append(rd32(i*4) & ~1)
cnt = collections.Counter(irq_addrs)
default_h = cnt.most_common(1)[0][0]
print(f"shared default handler @ 0x{FLASH+default_h:08x} (used by {cnt[default_h]} vectors)")
stm32f1_irq = {0:"WWDG",1:"PVD",2:"TAMPER",3:"RTC",4:"FLASH",5:"RCC",6:"EXTI0",7:"EXTI1",
8:"EXTI2",9:"EXTI3",10:"EXTI4",11:"DMA1_Ch1",12:"DMA1_Ch2",13:"DMA1_Ch3",14:"DMA1_Ch4",
15:"DMA1_Ch5",16:"DMA1_Ch6",17:"DMA1_Ch7",18:"ADC1_2",19:"USB_HP/CAN_TX",20:"USB_LP/CAN_RX0",
21:"CAN_RX1",22:"CAN_SCE",23:"EXTI9_5",24:"TIM1_BRK",25:"TIM1_UP",26:"TIM1_TRG_COM",
27:"TIM1_CC",28:"TIM2",29:"TIM3",30:"TIM4",31:"I2C1_EV",32:"I2C1_ER",33:"I2C2_EV",34:"I2C2_ER",
35:"SPI1",36:"SPI2",37:"USART1",38:"USART2",39:"USART3",40:"EXTI15_10",41:"RTCAlarm",
42:"USBWakeup",43:"TIM8_BRK",44:"TIM8_UP",45:"TIM8_TRG_COM",46:"TIM8_CC",47:"ADC3",48:"FSMC",
49:"SDIO",50:"TIM5",51:"SPI3",52:"UART4",53:"UART5",54:"TIM6",55:"TIM7",56:"DMA2_Ch1",
57:"DMA2_Ch2",58:"DMA2_Ch3",59:"DMA2_Ch4_5"}
print("\n=== USED peripheral IRQs (non-default handler) [STM32F1 names] ===")
for i,a in enumerate(irq_addrs):
    if a!=default_h and a!=0:
        print(f"  IRQ{i:3} {stm32f1_irq.get(i,'?'):14} -> 0x{FLASH+a:08x}")

# histogram peripheral base addresses referenced in literal pools (0x40000000-0x50000000)
print("\n=== peripheral addresses referenced (0x4000_0000-0x5000_0000), top 40 ===")
peri=collections.Counter()
for off in range(0, n-3, 4):
    v=rd32(off)
    if 0x40000000 <= v < 0x50000000:
        peri[v & 0xFFFFFF00]+=1   # bucket by 256
stm32f1_bases={0x40000000:"TIM2",0x40000400:"TIM3",0x40000800:"TIM4",0x40000c00:"TIM5",
0x40001000:"TIM6",0x40001400:"TIM7",0x40002800:"RTC",0x40002c00:"WWDG",0x40003000:"IWDG",
0x40003800:"SPI2",0x40003c00:"SPI3",0x40004400:"USART2",0x40004800:"USART3",0x40004c00:"UART4",
0x40005000:"UART5",0x40005400:"I2C1",0x40005800:"I2C2",0x40005c00:"USB",0x40006400:"CAN1",
0x40006800:"CAN2",0x40006c00:"BKP?",0x40007000:"PWR",0x40007400:"DAC",0x40010000:"AFIO",
0x40010400:"EXTI",0x40010800:"GPIOA",0x40010c00:"GPIOB",0x40011000:"GPIOC",0x40011400:"GPIOD",
0x40011800:"GPIOE",0x40011c00:"GPIOF",0x40012000:"GPIOG",0x40012400:"ADC1",0x40012800:"ADC2",
0x40012c00:"TIM1",0x40013000:"SPI1",0x40013400:"TIM8",0x40013800:"USART1",0x40013c00:"ADC3",
0x40020000:"DMA1",0x40020400:"DMA2",0x40021000:"RCC",0x40022000:"FLASH_IF",0x40023000:"CRC",
0x60000000:"FSMC",0xA0000000:"FSMC_R"}
for b,c in peri.most_common(40):
    print(f"  0x{b:08x}  x{c:<4} {stm32f1_bases.get(b,'')}")
