#!/usr/bin/env python3
"""lxp_pcap.py — dissect a Luxpower/EG4 dongle<->cloud packet capture.

The Wi-Fi datalogger ("dongle", docs/26) uploads the inverter's data to the EG4
cloud over TCP:4346 using the Luxpower datalogger protocol. That protocol wraps
the *same* EG4 Modbus device frames the dongle exchanges with the ARM on UART5
(docs/wiring/ARM-UART5), so a cloud-side capture is an oracle for the dongle<->ARM
link without a serial tap: the register windows the dongle reads and the values
the inverter returns are visible verbatim.

This is a pure-stdlib reader (no tshark/scapy needed). It does
Ethernet(+802.1Q VLAN) -> IPv4 -> TCP reassembly, then walks the outer frames:

    A1 1A | proto(u16 LE) | len(u16 LE) | addr(1) | tcp_func(1) | datalog_sn[10] | body

tcp_func 0xC1 = heartbeat, 0xC2 = data push. A data push body is an EG4 *device*
frame:

    dlen(u16 LE) | addr(1) | dev_func(1) | inverter_sn[10] | reg_start(u16 LE)
                 | nbytes(1) | payload[nbytes] | CRC16(LE)
    dev_func 0x03 = read-holding, 0x04 = read-input; registers little-endian;
    CRC-16/MODBUS (poly 0xA001, init 0xFFFF) over [addr .. payload].

What it prints:
  - default: the distinct (dev_func, reg_start, nbytes) windows the dongle ships,
    with CRC pass/fail counts — i.e. exactly which register banks are polled.
  - --reg N : decode the latest payload for reg_start N as little-endian u16s.
  - --per-pack : slice the IR 5000 bank (docs/34 §2b/§2d) into 30-register
    per-pack records and print each pack's register values + any ASCII run
    (e.g. the per-pack identity string). Field *semantics* live in docs/34.

The capture is a device artifact (it stays in the private lxp-factory repo, with
serials redacted in any public write-up); this tool only reads the path you give.

Usage:
  python3 tools/lxp_pcap.py capture.pcap
  python3 tools/lxp_pcap.py capture.pcap --reg 0
  python3 tools/lxp_pcap.py capture.pcap --reg 5000 --per-pack
  python3 tools/lxp_pcap.py capture.pcap --src 192.168.12.76 --dport 4346
"""
import sys
import struct
import argparse
from collections import Counter, OrderedDict


def crc16_modbus(b):
    crc = 0xFFFF
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def tcp_segments(path, want_src, want_dport):
    """Yield (seq, payload) for one direction, VLAN-aware."""
    d = open(path, "rb").read()
    magic = struct.unpack("<I", d[:4])[0]
    if magic not in (0xA1B2C3D4, 0xA1B23C4D):
        sys.exit("not a little-endian pcap (magic=0x%08x)" % magic)
    off = 24
    segs = []
    while off + 16 <= len(d):
        _, _, incl, _ = struct.unpack("<IIII", d[off:off + 16])
        off += 16
        pkt = d[off:off + incl]
        off += incl
        if len(pkt) < 18:
            continue
        et = struct.unpack(">H", pkt[12:14])[0]
        base = 14
        if et == 0x8100:  # 802.1Q VLAN tag
            et = struct.unpack(">H", pkt[16:18])[0]
            base = 18
        if et != 0x0800:
            continue
        ip = pkt[base:]
        if len(ip) < 20 or ip[9] != 6:  # IPv4 + TCP
            continue
        ihl = (ip[0] & 0xF) * 4
        src = ".".join(map(str, ip[12:16]))
        l4 = ip[ihl:]
        if len(l4) < 20:
            continue
        sp, dp = struct.unpack(">HH", l4[0:4])
        seq = struct.unpack(">I", l4[4:8])[0]
        doff = (l4[12] >> 4) * 4
        pl = l4[doff:]
        if pl and (want_src is None or src == want_src) and (want_dport is None or dp == want_dport):
            segs.append((seq, pl))
    segs.sort()
    out = bytearray()
    last = None
    for seq, pl in segs:
        if seq == last:
            continue
        out += pl
        last = seq
    return bytes(out)


def lxp_frames(s):
    i = 0
    out = []
    while i + 6 <= len(s):
        if s[i] != 0xA1 or s[i + 1] != 0x1A:
            j = s.find(b"\xa1\x1a", i + 1)
            if j < 0:
                break
            i = j
            continue
        flen = struct.unpack("<H", s[i + 4:i + 6])[0]
        total = 6 + flen
        if i + total > len(s):
            break
        out.append(s[i:i + total])
        i += total
    return out


def device_frame(f):
    """Parse a 0xC2 data push -> dict, or None. Offsets per the module docstring."""
    if f[7] != 0xC2 or len(f) < 36:
        return None
    dlen = struct.unpack("<H", f[18:20])[0]
    dev = f[20:20 + dlen]
    if len(dev) < 16:
        return None
    addr = dev[0]
    func = dev[1]
    reg = struct.unpack("<H", dev[32 - 20:34 - 20])[0]
    n = dev[34 - 20]
    payload = dev[15:15 + n]
    crc_rx = struct.unpack("<H", dev[15 + n:17 + n])[0] if len(dev) >= 17 + n else None
    crc_ok = (crc_rx == crc16_modbus(dev[:15 + n])) if crc_rx is not None else None
    return dict(addr=addr, func=func, reg=reg, n=n, payload=payload, crc_ok=crc_ok)


def regs_le(payload):
    return [struct.unpack("<H", payload[k:k + 2])[0] for k in range(0, len(payload) - 1, 2)]


def main():
    ap = argparse.ArgumentParser(description="Dissect a Luxpower dongle<->cloud pcap")
    ap.add_argument("pcap")
    ap.add_argument("--src", default=None, help="dongle IP (default: busiest TCP talker)")
    ap.add_argument("--dport", type=int, default=4346, help="cloud TCP port (default 4346)")
    ap.add_argument("--reg", type=int, default=None, help="decode latest window at this reg_start")
    ap.add_argument("--per-pack", action="store_true", help="slice a 5000-style bank, 30 regs/pack")
    a = ap.parse_args()

    src = a.src
    if src is None:  # pick the host that sent the most bytes to :dport
        d = open(a.pcap, "rb").read()
        off = 24
        tally = Counter()
        while off + 16 <= len(d):
            _, _, incl, _ = struct.unpack("<IIII", d[off:off + 16]); off += 16
            pkt = d[off:off + incl]; off += incl
            if len(pkt) < 18:
                continue
            et = struct.unpack(">H", pkt[12:14])[0]; base = 14
            if et == 0x8100:
                et = struct.unpack(">H", pkt[16:18])[0]; base = 18
            if et != 0x0800:
                continue
            ip = pkt[base:]
            if len(ip) < 20 or ip[9] != 6:
                continue
            ihl = (ip[0] & 0xF) * 4; l4 = ip[ihl:]
            if len(l4) < 20:
                continue
            _, dp = struct.unpack(">HH", l4[0:4])
            if dp == a.dport:
                tally[".".join(map(str, ip[12:16]))] += len(l4) - (l4[12] >> 4) * 4
        if tally:
            src = tally.most_common(1)[0][0]
    stream = tcp_segments(a.pcap, src, a.dport)
    frames = lxp_frames(stream)
    print("dongle %s -> :%d   reassembled %d bytes, %d Luxpower frames"
          % (src, a.dport, len(stream), len(frames)))

    windows = OrderedDict()  # (func,reg,n) -> [count, crc_ok_count, latest_payload]
    tcpfn = Counter()
    for f in frames:
        tcpfn[f[7]] += 1
        df = device_frame(f)
        if not df:
            continue
        k = (df["func"], df["reg"], df["n"])
        w = windows.setdefault(k, [0, 0, None])
        w[0] += 1
        w[1] += 1 if df["crc_ok"] else 0
        w[2] = df["payload"]
    print("tcp_function: " + ", ".join("0x%02x x%d" % (k, v) for k, v in tcpfn.items()))
    print("=== register windows polled (dev_func, reg_start, nbytes): count, crc_ok ===")
    for (func, reg, n), (c, ok, _) in windows.items():
        print("  func=0x%02x reg=%-5d nbytes=%-3d (%d regs)  x%-3d  crc_ok=%d/%d"
              % (func, reg, n, n // 2, c, ok, c))

    if a.reg is not None:
        pl = next((w[2] for k, w in windows.items() if k[1] == a.reg), None)
        if pl is None:
            print("no window with reg_start=%d" % a.reg); return
        r = regs_le(pl)
        if a.per_pack:
            STRIDE = 30
            for p in range(len(r) // STRIDE):
                blk = r[p * STRIDE:(p + 1) * STRIDE]
                if not any(blk):
                    continue
                raw = b"".join(struct.pack("<H", v) for v in blk)
                import re
                txt = [m.group().decode("latin1") for m in re.finditer(rb"[ -~]{3,}", raw)]
                print("  pack %d @ reg %d: %s%s"
                      % (p, a.reg + p * STRIDE, blk,
                         ("   ascii=%r" % txt) if txt else ""))
        else:
            for k in range(0, len(r), 8):
                print("  reg %-5d: %s" % (a.reg + k, " ".join("%5d" % v for v in r[k:k + 8])))


if __name__ == "__main__":
    main()
