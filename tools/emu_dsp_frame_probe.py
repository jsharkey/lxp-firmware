#!/usr/bin/env python3
"""
BE-mode (DSP-path) frame probe for the ARM->DSP serializer.

Background (see docs/08 "CORRECTION" + docs/10). The ARM frame serializer
sub_0803373c is dual-mode, switched by RAM flag 0x2000aa0b bit 0:
  * bit0 = 0  -> dongle path: SN[10] copied, little-endian values
  * bit0 = 1  -> DSP path:    no SN,         big-endian values
This probe drives the DSP path (bit0 = 1) so the captured frame matches what the
DSP's FUN_00092EE2 ingests, and recovers register -> frame-offset by stubbing the
register getter fn_ceaa (0x08032000) to return the register number itself -- so
each 16-bit big-endian value in the frame *is* its source register number.

Goal: align these offsets against docs/10's per-block layout so the full
regs 64-89 (battery charge/discharge schedule) -> DSP RAM target map closes with
proof on both ends.

Prereqs: reference/ceaa-07xx_vE_260214.bin (from tools/hex2bin.py on the ARM .hex) and
reference/symbols.csv (from tools/recurse.py). Read-only; sandboxed.

Usage:
  python3 tools/emu_dsp_frame_probe.py                 # func=3, group 40-79
  python3 tools/emu_dsp_frame_probe.py 3 80 40         # func, start, count
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))
from emu import Emu
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_LR, UC_ARM_REG_PC

RX       = 0x20007490     # USART3 link buffer (request lands here)
FRAME    = 0x20009414     # response frame built here (sent by sub_08015094)
BUILDER  = 0x08014fec     # dispatches on [RX+1]: 3/4 read, 6/0x10 write
FN_CEAA  = 0x08032000     # per-register value getter: r0 = reg number -> value
MODEFLAG = 0x2000aa0b     # bit0: 0 = dongle (LE+SN), 1 = DSP (BE, no SN)

def probe(func=3, start=40, count=40):
    emu = Emu("reference/ceaa-07xx_vE_260214.bin", "reference/symbols.csv")
    # --- DSP path ---
    emu.uc.mem_write(MODEFLAG, b"\x01")
    # --- request: addr, func, and (BE-path) start@RX+2, count@RX+4 big-endian ---
    emu.wbytes(RX, bytes(0x100))
    emu.uc.mem_write(RX + 0, bytes([0x01, func & 0xff]))
    emu.uc.mem_write(RX + 0x02, struct.pack(">H", start))
    emu.uc.mem_write(RX + 0x04, struct.pack(">H", count))
    # --- make fn_ceaa return the register number it was asked for (r0) ---
    def on_ceaa(uc, addr, size, ud):
        if addr == (FN_CEAA & ~1) or addr == FN_CEAA:
            reg = uc.reg_read(UC_ARM_REG_R0) & 0xffff
            uc.reg_write(UC_ARM_REG_R0, reg)          # value := register number
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    emu.uc.hook_add(UC_HOOK_CODE, on_ceaa, begin=FN_CEAA & ~1, end=(FN_CEAA & ~1) + 2)
    emu.wbytes(FRAME, bytes([0xEE] * 0xC0))
    emu.watch = (FRAME, FRAME + 0xC0)
    emu.call(BUILDER, (0, RX, 0x40))
    frame = {o - FRAME: v for (pc, o, sz, v) in emu.mem_writes}
    return frame

def main():
    args = [int(x, 0) for x in sys.argv[1:]]
    func  = args[0] if len(args) > 0 else 3
    start = args[1] if len(args) > 1 else 40
    count = args[2] if len(args) > 2 else 40
    f = probe(func, start, count)
    hi = max(f) if f else 0
    raw = bytes(f.get(i, 0) for i in range(hi + 1))
    print("DSP-path (0x2000aa0b=1) frame, func=%d start=%d count=%d" % (func, start, count))
    print("raw bytes:")
    print("  " + " ".join("%02x" % b for b in raw))
    print("\nbig-endian u16 values (fn_ceaa stubbed to echo the register number):")
    print("  off : value  (value == source register, if a register slot)")
    for off in range(0, len(raw) - 1):
        be = (raw[off] << 8) | raw[off + 1]
        if start <= be < start + count:        # looks like a register number in range
            print("  0x%02x : reg %d" % (off, be))
    print("\nInterpretation: a 'reg N' at offset O means register N's value is written")
    print("at frame byte O (big-endian). Cross-check O against docs/10's block layout.")

if __name__ == "__main__":
    if not os.path.exists("reference/ceaa-07xx_vE_260214.bin"):
        sys.exit("need reference/ceaa-07xx_vE_260214.bin (run tools/hex2bin.py on the ARM .hex)")
    main()
