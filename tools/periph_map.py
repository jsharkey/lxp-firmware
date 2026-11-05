#!/usr/bin/env python3
"""
Peripheral overview for the ARM 'com' MCU: which on-chip peripherals the
firmware actually uses, found by scanning literal pools for peripheral base
addresses (and their bit-band aliases). Complements tools/gpio_map.py, which
maps the pins; here you see which UART/SPI/CAN/timer blocks own the AF pins.

Read-only static scan. Usage: python3 tools/periph_map.py [flat.bin] [symbols.csv]
   defaults: reference/com_flat.bin  reference/symbols.csv
"""
import sys, struct, bisect, csv
from collections import defaultdict

FW  = sys.argv[1] if len(sys.argv) > 1 else "reference/com_flat.bin"
SYM = sys.argv[2] if len(sys.argv) > 2 else "reference/symbols.csv"
BASE = 0x08000000
d = open(FW, "rb").read(); N = len(d)
funcs = sorted(int(r["addr"], 16) for r in csv.DictReader(open(SYM)))
def fof(a):
    i = bisect.bisect_right(funcs, a) - 1
    return funcs[i] if i >= 0 else 0

PER = {
    0x40013800:"USART1",0x40004400:"USART2",0x40004800:"USART3",0x40004c00:"UART4",
    0x40005000:"UART5",0x40013000:"SPI1",0x40003800:"SPI2",0x40006400:"CAN1",
    0x40005400:"I2C1",0x40005800:"I2C2",0x40012c00:"TIM1",0x40000000:"TIM2",
    0x40000400:"TIM2",0x40000800:"TIM3",0x40000c00:"TIM4",0x40013400:"TIM8",
    0x40012400:"ADC1",0x40012800:"ADC2",0x40013c00:"ADC3",0x40006c00:"BKP",
    0x40007000:"PWR",0x40002800:"RTC",0x40003000:"IWDG",0x40002c00:"WWDG",
    0x40010000:"AFIO",0x40010400:"EXTI",0x40010800:"GPIOA",0x40010c00:"GPIOB",
    0x40011000:"GPIOC",0x40011400:"GPIOD",0x40011800:"GPIOE",0x40021000:"RCC",
}
hit = defaultdict(set); bb = defaultdict(int)
for o in range(0, N-3):
    w = struct.unpack_from("<I", d, o)[0]
    if w in PER:
        hit[PER[w]].add(fof(BASE+o))
    elif 0x42000000 <= w < 0x44000000:
        pa = 0x40000000 + (w-0x42000000)//32
        pb = pa & 0xFFFFFC00
        if pb in PER: bb[PER[pb]] += 1

print("# peripheral base referenced -> # distinct functions that load it")
for name in sorted(hit, key=lambda k: -len(hit[k])):
    fns = sorted(hit[name])
    print("  %-7s x%-2d  %s" % (name, len(fns), " ".join("0x%08x"%a for a in fns[:6])))
print("\n# peripheral bit-band (0x42xxxxxx) single-bit access counts")
for name, c in sorted(bb.items(), key=lambda kv:-kv[1]):
    print("  %-7s %d" % (name, c))
