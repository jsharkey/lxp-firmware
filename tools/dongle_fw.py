#!/usr/bin/env python3
"""dongle_fw.py — analyzer for the external monitoring *dongle* firmware.

This is the peer on the other end of the inverter's external "RS-485 / Modbus"
port (see docs/16, docs/26). Unlike the inverter com-MCU (STM32F103, ARM Thumb,
flash @ 0x08000000) or the battery BMS (HC32, tools/batt_canmap.py), the dongle
is an **Espressif ESP32-C3** (RISC-V RV32IMC) running an ESP-IDF application
built on the HIDO IoT SDK.

What it reports, from an ESP-IDF v2 application image (magic 0xE9):
  - header: chip id, entry, segment map (DROM/DRAM/IRAM/IROM) with load addrs
  - app descriptor: project name, version, build date, IDF version
  - --disasm LO HI : RV32 disassembly of a virtual-address range (needs capstone
    with the RISC-V backend); reconstructs lui/addi/auipc immediates and
    annotates string/baud operands
  - --bauds        : every immediate-load site equal to a standard baud rate
  - --str SUBSTR   : .rodata strings matching SUBSTR and the code addrs that
    reference them (via reconstructed lui/addi/auipc absolute addresses)

The whole point (docs/26): the RS-485 init hardcodes UART_MODE_RS485_HALF_DUPLEX
and the dongle is the bus *master* (datalogger) — which fixes the ARM end of the
link to UART5 (ARM = slave), not USART3 (ARM = master toward the DSP).

Usage:
  python3 -I tools/dongle_fw.py <dongle.bin>
  python3 -I tools/dongle_fw.py <dongle.bin> --disasm 0x4200c480 0x4200c620
  python3 -I tools/dongle_fw.py <dongle.bin> --bauds
  python3 -I tools/dongle_fw.py <dongle.bin> --str HALF_DUPLEX

The image is a proprietary factory image and is NOT committed (reference/*.bin
is gitignored); point this at your local copy. It is untrusted data: this tool
only *reads* it, and should be run with an isolated interpreter (`python3 -I`).
"""
import sys
import struct
import argparse

STD_BAUDS = {2400, 4800, 9600, 19200, 38400, 57600, 74880, 115200, 230400, 921600}


def parse(path):
    d = open(path, "rb").read()
    magic, seg_count, _mode, _ss, entry = struct.unpack("<BBBBI", d[:8])
    if magic != 0xE9:
        sys.exit("not an ESP-IDF image (magic=0x%02x)" % magic)
    chip_id = struct.unpack("<H", d[12:14])[0]
    off, segs = 24, []
    for _ in range(seg_count):
        load, length = struct.unpack("<II", d[off:off + 8])
        off += 8
        segs.append((load, length, off))
        off += length
    return d, entry, chip_id, segs


def region(load):
    if 0x40000000 <= load < 0x40900000:
        return "IRAM"
    if load >= 0x42000000:
        return "IROM (flash .text)"
    if 0x3FC00000 <= load < 0x3FD00000:
        return "DRAM"
    if 0x3C000000 <= load < 0x3D000000:
        return "DROM (flash .rodata)"
    return "?"


def read_va(d, segs, va, n):
    for load, length, fo in segs:
        if load <= va < load + length:
            o = fo + (va - load)
            return d[o:o + n]
    return b""


def cstr(d, segs, va, maxlen=160):
    b = read_va(d, segs, va, maxlen)
    z = b.find(b"\x00") if b else -1
    if z <= 0:
        return None
    try:
        t = b[:z].decode("ascii")
    except UnicodeDecodeError:
        return None
    return t if all(32 <= ord(c) < 127 or c == "\t" for c in t) else None


def header(d, entry, chip_id, segs):
    chip = {5: "ESP32-C3"}.get(chip_id, "id %d" % chip_id)
    print("chip=%s  entry=0x%08x  segments=%d" % (chip, entry, len(segs)))
    for i, (load, length, fo) in enumerate(segs):
        print("  seg %d load=0x%08x len=%-7d fileoff=0x%06x  %s"
              % (i, load, length, fo, region(load)))
    for load, length, fo in segs:
        if d[fo:fo + 4] == b"\x32\x54\xcd\xab":  # esp_app_desc_t magic 0xABCD5432
            desc = d[fo:fo + 256]
            g = lambda a, b: desc[a:b].split(b"\x00")[0].decode("latin1")
            print("APP_DESC: project=%r version=%r built=%r %r idf=%r"
                  % (g(48, 80), g(16, 48), g(96, 112), g(80, 96), g(112, 144)))


def _iter_code(d, segs):
    from capstone import Cs, CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC
    md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
    md.detail = True
    for load, length, fo in segs:
        if region(load) in ("IRAM", "IROM (flash .text)"):
            for ins in md.disasm(d[fo:fo + length], load):
                yield ins


def _track(ins, reg):
    """Reconstruct simple lui/auipc/addi/li immediates into reg[], returning the
    (dest, value) just produced, or (None, None)."""
    m, op = ins.mnemonic, ins.op_str
    try:
        if m in ("lui", "c.lui"):
            p = op.replace(",", " ").split()
            reg[p[0]] = (int(p[-1], 0) << 12) & 0xFFFFFFFF
            return p[0], reg[p[0]]
        if m == "auipc":
            p = op.replace(",", " ").split()
            reg[p[0]] = (ins.address + (int(p[-1], 0) << 12)) & 0xFFFFFFFF
            return p[0], reg[p[0]]
        if m in ("c.li", "li"):
            p = op.replace(",", " ").split()
            reg[p[0]] = int(p[-1], 0) & 0xFFFFFFFF
            return p[0], reg[p[0]]
        if m in ("c.mv", "mv"):
            p = op.replace(",", " ").split()
            reg[p[0]] = reg.get(p[-1])
            return p[0], reg[p[0]]
        if m in ("addi", "c.addi", "addiw", "c.addiw"):
            p = op.replace(",", " ").split()
            rd = p[0]
            rs = p[1] if len(p) >= 3 else rd
            reg[rd] = ((reg.get(rs) or 0) + int(p[-1], 0)) & 0xFFFFFFFF
            return rd, reg[rd]
        # other ops clobber their destination register
        dst = op.split(",")[0].strip()
        if dst in reg:
            reg[dst] = None
    except Exception:
        pass
    return None, None


def disasm(d, segs, lo, hi):
    from capstone import Cs, CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC
    md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
    data = read_va(d, segs, lo, hi - lo)
    reg = {}
    for ins in md.disasm(data, lo):
        _, v = _track(ins, reg)
        note = ""
        if v:
            s = cstr(d, segs, v)
            if s:
                note = '  ; "%s"' % s[:70]
            elif v in STD_BAUDS:
                note = "  ; BAUD %d" % v
        if ins.mnemonic in ("jal", "c.jal", "jalr", "c.jalr"):
            note += "  [CALL]"
        print("0x%08x  %-10s %-26s%s" % (ins.address, ins.mnemonic, ins.op_str, note))


def bauds(d, segs):
    reg = {}
    seen = set()
    for ins in _iter_code(d, segs):
        _, v = _track(ins, reg)
        if v in STD_BAUDS and (ins.address, v) not in seen:
            seen.add((ins.address, v))
            print("0x%08x  baud=%-6d  (%s %s)" % (ins.address, v, ins.mnemonic, ins.op_str))


def strsearch(d, segs, needle):
    import collections
    refs = collections.defaultdict(list)
    reg = {}
    for ins in _iter_code(d, segs):
        _, v = _track(ins, reg)
        if v and 0x3C000000 <= v < 0x3D000000:
            s = cstr(d, segs, v)
            if s is not None:
                refs[v].append(ins.address)
    for va in sorted(refs):
        s = cstr(d, segs, va)
        if needle.lower() in s.lower():
            rs = sorted(set(refs[va]))
            print("str@0x%08x %r  <- %s"
                  % (va, s, ", ".join("0x%08x" % a for a in rs[:8])))


def main():
    ap = argparse.ArgumentParser(description="ESP32-C3 dongle firmware analyzer (docs/26)")
    ap.add_argument("image")
    ap.add_argument("--disasm", nargs=2, metavar=("LO", "HI"))
    ap.add_argument("--bauds", action="store_true")
    ap.add_argument("--str", dest="needle")
    a = ap.parse_args()
    d, entry, chip_id, segs = parse(a.image)
    if a.disasm:
        disasm(d, segs, int(a.disasm[0], 0), int(a.disasm[1], 0))
    elif a.bauds:
        bauds(d, segs)
    elif a.needle is not None:
        strsearch(d, segs, a.needle)
    else:
        header(d, entry, chip_id, segs)


if __name__ == "__main__":
    main()
