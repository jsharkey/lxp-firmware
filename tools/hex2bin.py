#!/usr/bin/env python3
"""
Intel HEX -> correctly-addressed flat binary.

IMPORTANT: the vendor's raw .bin dumps are a concatenation of non-contiguous
flash regions with the gaps removed, so byte offsets in the .bin do NOT equal
(flash_addr - 0x08000000). All reverse-engineering must be done against the
flat image produced here (gaps filled with 0xFF, every byte at its true flash
address), or references via literal pools / pointer tables will not resolve.

Usage: python3 hex2bin.py firmware.hex [out_flat.bin] [--base 0x08000000]
If the output path is omitted, the flat image is named after the input .hex
(reference/<hex basename>.bin), so the filename says which firmware it is.
Prints the recovered segment map.
"""
import os, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument("hex")
ap.add_argument("out", nargs="?",
                help="output .bin (default: reference/<hex basename>.bin)")
ap.add_argument("--base", default="0x08000000")
ap.add_argument("--fill", default="0xFF")
args = ap.parse_args()
BASE = int(args.base, 0); FILL = int(args.fill, 0) & 0xFF
out = args.out or os.path.join("reference",
                               os.path.splitext(os.path.basename(args.hex))[0] + ".bin")

mem = {}
linbase = 0
for ln in open(args.hex):
    ln = ln.strip()
    if not ln.startswith(":"):
        continue
    b = bytes.fromhex(ln[1:])
    n = b[0]; addr = (b[1] << 8) | b[2]; typ = b[3]; data = b[4:4+n]
    # checksum check
    if (sum(b) & 0xFF) != 0:
        sys.exit(f"bad checksum: {ln}")
    if typ == 0x00:
        for i, by in enumerate(data):
            mem[linbase + addr + i] = by
    elif typ == 0x04:
        linbase = ((data[0] << 8) | data[1]) << 16
    elif typ == 0x02:
        linbase = ((data[0] << 8) | data[1]) << 4
    elif typ == 0x01:
        break

addrs = sorted(mem)
lo, hi = addrs[0], addrs[-1]
flat = bytearray([FILL]) * (hi - BASE + 1)
for a, by in mem.items():
    flat[a - BASE] = by
open(out, "wb").write(flat)

# segment map
segs = []
s = p = addrs[0]
for a in addrs[1:]:
    if a != p + 1:
        segs.append((s, p)); s = a
    p = a
segs.append((s, p))
print(f"base 0x{BASE:08x}  span 0x{lo:08x}..0x{hi:08x}  bytes present {len(mem)}  flat size {len(flat)}")
print("segments (true flash addresses):")
for s, e in segs:
    print(f"  0x{s:08x} .. 0x{e:08x}   {e-s+1} bytes")
print(f"wrote {out}")
