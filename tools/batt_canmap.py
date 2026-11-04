#!/usr/bin/env python3
"""batt_canmap.py — first-pass analyzer for the EG4 *battery* BMS firmware.

This is the peer on the other end of the inverter's "CAN1 / battery BMS bus"
(see docs/16). Unlike the inverter com-MCU (STM32F103, flash @ 0x08000000),
the battery runs a **Huada/HDSC HC32-family** Cortex-M part and the factory
image is a flat **App** partition that loads at **0x00020000** (a bootloader
lives below it, 0x00000000-0x00020000). Vectors therefore read 0x0002xxxx.

What it reports, from a flat App image:
  - vector table summary (initial SP, reset, populated IRQ count)
  - HC32 peripheral-page histogram (which blocks the code touches)
  - the CAN TX frame-ID descriptor table (SMA/Victron 0x3xx family)
  - the selectable inverter-brand protocol presets ("Pnn-XXX")
  - model / chemistry / version identity strings

Vector/peripheral decode is generic Cortex-M; the frame-table and preset
heuristics are specific to this battery image family.

Usage:
  python3 tools/batt_canmap.py <flat_app.bin> [--base 0x20000]

The binary itself is a proprietary factory image and is NOT committed
(reference/*.bin is gitignored); point this at your local copy.
"""
import sys, struct, argparse, re

# HC32F460-class peripheral pages (base & file-driven; labels are best-effort,
# confirmed by usage, not by a vendor header we have on hand).
HC32_PERIPH = {
    0x40010400: "EFM (embedded flash)",
    0x40021000: "CAN controller",
    0x40021400: "CAN (mailbox/RAM window)",
    0x4001D000: "USART (RS485 link)",
    0x4001D400: "USART (RS485 link)",
    0x40054000: "INTC / AOS (interrupt routing)",
    0x40053000: "PORT / GPIO",
    0x40053800: "PORT / GPIO",
    0x40050800: "TMR / watchdog window",
    0x40051000: "TMR",
    0x40048000: "SPI / I2C",
    0x4000F000: "FCG / RMU (clock-gate / reset)",
}

# 11-bit CAN IDs of the de-facto inverter "CAN bus battery" protocol
# (SMA/Victron/Pylontech-compatible 0x3xx family).
KNOWN_3XX = {
    0x305: "inverter->batt keep-alive",
    0x307: "inverter->batt",
    0x351: "charge voltage / current limits",
    0x355: "SOC / SOH",
    0x356: "battery V / I / T",
    0x359: "protection & alarm flags",
    0x35a: "alarms / warnings",
    0x35b: "extended status",
    0x35c: "charge request flags",
    0x35e: "manufacturer name",
    0x35f: "firmware / capacity info",
}


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def vectors(b, base):
    sp, reset = u32(b, 0), u32(b, 4)
    irq = 0
    for i in range(16, 496):
        if 4 * i + 4 > len(b):
            break
        w = u32(b, 4 * i)
        if base <= w < base + 0x200000 and (w & 1):
            irq += 1
        elif w == 0:
            continue
        else:
            break
    print("== vector table ==")
    print(f"  initial SP : 0x{sp:08x}")
    print(f"  reset      : 0x{reset:08x}  (file +0x{(reset & ~1) - base:x})")
    print(f"  IRQ vectors: {irq} populated")


def periph(b, base):
    from collections import Counter
    c = Counter()
    for o in range(0, len(b) - 3, 4):
        w = u32(b, o)
        if 0x40000000 <= w < 0x40060000:
            c[w & 0xFFFFFF00] += 1
    print("\n== peripheral refs (top pages) ==")
    for k, n in c.most_common(14):
        print(f"  0x{k:08x} x{n:<3} {HC32_PERIPH.get(k & 0xFFFFF000, HC32_PERIPH.get(k, ''))}")


def frame_table(b, base):
    # entries are 32-bit words whose low half is an 11-bit CAN ID (<0x800),
    # laid out contiguously (>=6 in a row 4 bytes apart).
    print("\n== CAN TX frame-ID table(s) ==")
    o = 0
    runs = []
    cur = []
    while o < len(b) - 3:
        w = u32(b, o)
        if w != 0 and (w & 0xFFFF0000) == 0 and 0x100 <= (w & 0xFFFF) < 0x800:
            cur.append((o, w & 0xFFFF))
        else:
            if len(cur) >= 6:
                runs.append(cur)
            cur = []
        o += 4
    if len(cur) >= 6:
        runs.append(cur)
    for r in runs:
        print(f"  table @ 0x{base + r[0][0]:08x}  ({len(r)} entries):")
        line = []
        for _, cid in r:
            note = KNOWN_3XX.get(cid)
            line.append(f"0x{cid:03x}" + (f"({note.split('/')[0].strip()})" if note else ""))
        # wrap
        for i in range(0, len(line), 6):
            print("    " + "  ".join(line[i:i + 6]))


def presets(b, base):
    print("\n== inverter-brand protocol presets & identity ==")
    seen = []
    for m in re.finditer(rb"[ -~]{3,}", b):
        s = m.group().decode()
        if re.match(r"P\d\d-[A-Z]", s) or s in (
            "EG4/LUX",
        ) or re.search(r"(EG4|LFP|Ah-V|LUX|M\d\d\.\d|51\.2V|\d{4}-\d\d-\d\d)", s):
            if s not in (x[1] for x in seen):
                seen.append((base + m.start(), s))
    for a, s in seen:
        print(f"  0x{a:08x}  {s!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bin")
    ap.add_argument("--base", default="0x20000",
                    help="flat load base of the App partition (default 0x20000)")
    a = ap.parse_args()
    base = int(a.base, 0)
    b = open(a.bin, "rb").read()
    print(f"image {a.bin}  base=0x{base:08x}  size={len(b)} (0x{len(b):x})")
    vectors(b, base)
    periph(b, base)
    frame_table(b, base)
    presets(b, base)


if __name__ == "__main__":
    main()
