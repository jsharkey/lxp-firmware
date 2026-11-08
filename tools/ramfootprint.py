#!/usr/bin/env python3
"""
Measure how much SRAM a booted ARM image actually uses — and how much is free.

Method (dynamic, black-box): fill all 64 KB of SRAM with a per-word *address*
sentinel (mem[a] == a), boot the image from its own reset vector (the C startup
then zeroes .bss and copies .data), run its super-loop for a while with SysTick
firing, and read SRAM back. A word still equal to its own address was never
written -> free. Everything else is .data + .bss + whatever the stack and any
runtime buffers touched. The factory image needs a provisioned config flash to
clear its boot gate, so one is attached (does not consume MCU SRAM).

Caveat: this counts *writes*. A byte only read, or reserved inside a stack frame
but never written, reads as "free", so the stack's true worst case can dip below
the observed low-water — leave margin. The static (.data+.bss) figure is exact.

Usage: python3 tools/ramfootprint.py <flat.bin> [boot_insn] [run_insn]
Requires: pip install unicorn. Read-only; nothing is modified.
"""
import sys, struct
sys.path.insert(0, "tools")
from arm_sim import ArmSim

RAM, SIZE = 0x20000000, 0x10000

def main():
    img = sys.argv[1]
    boot = int(sys.argv[2]) if len(sys.argv) > 2 else 3_000_000
    run = int(sys.argv[3]) if len(sys.argv) > 3 else 6_000_000

    sim = ArmSim(img)
    sim.attach_config_flash()                      # clears the factory boot gate
    sim.enable_systick(2000)
    sp0 = sim.r32(sim.vector_base())
    sim.uc.mem_write(RAM, b"".join(
        struct.pack("<I", (RAM + i * 4) & 0xFFFFFFFF) for i in range(SIZE // 4)))
    sim.run_reset(max_insn=boot)
    sim.run(run)

    buf = bytes(sim.uc.mem_read(RAM, SIZE))
    used = [struct.unpack_from("<I", buf, i * 4)[0] != ((RAM + i * 4) & 0xFFFFFFFF)
            for i in range(SIZE // 4)]
    # runs
    runs, i = [], 0
    while i < len(used):
        j = i
        while j < len(used) and used[j] == used[i]:
            j += 1
        runs.append((used[i], RAM + i * 4, RAM + j * 4))
        i = j
    static_top = next((a for u, a, b in runs if not u), RAM)  # top of the low used block
    for u, a, b in runs:
        if u and a == RAM:
            static_top = b
            break
    touched = sum(u for u in used) * 4
    free = SIZE - touched
    biggest = max(((b - a) for u, a, b in runs if not u), default=0)
    print(f"image            : {img}")
    print(f"initial SP       : 0x{sp0:08x}")
    print(f"SRAM total       : {SIZE} B (64.0 KB)")
    print(f"static .data+.bss: 0x20000000..0x{static_top:08x}  {static_top-RAM} B ({(static_top-RAM)/1024:.1f} KB)")
    print(f"touched (used)   : {touched} B ({touched/1024:.1f} KB)")
    print(f"free (untouched) : {free} B ({free/1024:.1f} KB)  largest run {biggest} B ({biggest/1024:.1f} KB)")
    print("free runs >= 256 B:")
    for u, a, b in runs:
        if not u and (b - a) >= 256:
            where = "above SP" if a >= sp0 else "below SP"
            print(f"  0x{a:08x}..0x{b:08x}  {b-a:6d} B ({(b-a)/1024:4.1f} KB)  [{where}]")

if __name__ == "__main__":
    main()
