#!/usr/bin/env python3
"""
Dump a Cortex-M vector table and locate the firmware's VTOR.

Works on a correctly-addressed flat image (see tools/hex2bin.py). The vector
table is NOT always at the flash base: monolithic images put it at 0x08000000,
but a bootloader + "App" image relocates it (the EG4 18kPV App is at 0x0800C800;
the 12000XP 07-series App is at 0x08005000). Point --vt at wherever vector[0]
(initial SP) and vector[1] (reset) actually live; if you omit it, the flash base
is assumed.

Usage:
  python3 tools/vt.py flat.bin [--base 0x08000000] [--vt 0x08005000] [--count 24]

Prints the initial SP, the reset handler, the first N vectors, and the reset
stub disassembly if capstone is installed. Also scans for the SCB->VTOR write
(literal matching --vt near a reference to 0xE000ED08) to confirm the table's
true base.
"""
import sys, struct, argparse

ap = argparse.ArgumentParser()
ap.add_argument("bin")
ap.add_argument("--base", default="0x08000000")
ap.add_argument("--vt", default=None, help="vector-table address (default: base)")
ap.add_argument("--count", type=int, default=24)
args = ap.parse_args()

BASE = int(args.base, 0)
data = open(args.bin, "rb").read()
VT = int(args.vt, 0) if args.vt else BASE

def rd32(addr):
    o = addr - BASE
    if 0 <= o <= len(data) - 4:
        return struct.unpack_from("<I", data, o)[0]
    return None

sp, rst = rd32(VT), rd32(VT + 4)
print(f"image {args.bin}  base=0x{BASE:08x}  vt=0x{VT:08x}  size={len(data)}")
if sp is None or rst is None:
    sys.exit("vector table address is outside the image")
print(f"vector[0] initial SP = 0x{sp:08x}")
print(f"vector[1] reset      = 0x{rst:08x}")
print(f"first {args.count} vectors:")
for i in range(args.count):
    v = rd32(VT + 4 * i)
    print(f"  [{i:2}] 0x{VT+4*i:08x} -> " + (f"0x{v:08x}" if v is not None else "(absent)"))

# Confirm VTOR: a build that relocates its table writes SCB->VTOR (0xE000ED08)
# with the table base as a literal. Report where that literal appears.
def find_word(val):
    return [BASE + o for o in range(0, len(data) - 3, 4)
            if struct.unpack_from("<I", data, o)[0] == val]
vtor_refs = find_word(VT)
scb_refs = find_word(0xE000ED08)
print(f"\nliteral 0x{VT:08x} (candidate VTOR value) at: "
      + (", ".join(f"0x{a:08x}" for a in vtor_refs[:6]) or "(none)"))
print(f"SCB->VTOR reg 0xE000ED08 referenced at: "
      + (", ".join(f"0x{a:08x}" for a in scb_refs[:6]) or "(none)"))

# Optional: disassemble the reset stub.
try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    tgt = rst & ~1
    o = tgt - BASE
    if 0 <= o < len(data):
        print(f"\nreset stub @ 0x{tgt:08x}:")
        for ins in md.disasm(data[o:o + 16], tgt):
            print(f"  0x{ins.address:08x}  {ins.bytes.hex():10} {ins.mnemonic:6} {ins.op_str}")
except ImportError:
    print("\n(install capstone for reset-stub disassembly)")
