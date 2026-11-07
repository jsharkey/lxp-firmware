#!/usr/bin/env python3
"""
HR write -> DSP config-push matrix (docs/39 T25). For each writable holding
register, write two distinct in-range values on the factory image and diff the
resulting config-frame payloads, reporting which block/offset each register moves
-- or "none (ARM-local only)".

Method note (why two *fresh* single-write captures, not push_delta):
  The differential `push_delta(reg, A, B)` writes A then B on ONE sim, so a byte
  that changes only because the second write follows the first (modbus-transaction
  residue) is a FALSE POSITIVE -- that is how "HR 75 -> block 4 0x26" was wrongly
  "verified". Here each value is written on its OWN fresh boot, so a byte that
  differs between the two captures is driven by the register's VALUE, not by the
  act of writing. Value-dependent residue still lands only at payload 0x15/0x16 and
  block 0 0x25/0x26 (shared modbus-RX buffer); those are classified as residue, not
  fields.

Read-only; needs unicorn + the factory flat image. Usage:
  python3 tools/dsp_push_matrix.py [IMAGE] [--md OUT.md]
Default IMAGE: reference/com_flat.bin (fallback reference/ceaa-07xx_vE_260214.bin).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests")]
from dsppush_contract import FactoryBackend  # noqa: E402

NBLOCKS = 9
PAY_LO, PAY_HI = 0x15, 0x34

# Residue offsets (shared modbus-RX-buffer bleed, value-dependent but not a field):
# payload 0x15/0x16 in any block, and block 0's 0x25/0x26.
def is_residue(blk, off):
    return off in (0x15, 0x16) or (blk == 0 and off in (0x25, 0x26))

# (reg, name, A, B) -- two distinct in-range values. Ranges from modbus_map.h.
WIN_A, WIN_B = (9 << 0) | (10 << 8), (21 << 0) | (34 << 8)   # 09:10 vs 21:34
CANDIDATES = [
    (9,  "SLAVE_COM_VER",   0, 1),
    (11, "RESET_SETTING",   0, 0),      # write 0/0: side-effect reg, keep inert
    (15, "COM_ADDR",        1, 5),
    (16, "LANGUAGE",        0, 1),
    (20, "PV_INPUT_MODEL",  1, 4),
    (21, "FUNC_EN",         1, 2),
    (22, "START_PV_VOLT",   1000, 3000),
    (23, "CONNECT_TIME",    30, 300),
    (24, "RECONNECT_TIME",  0, 300),
    (59, "REACTIVE_CMD_TYPE", 1, 4),
    (60, "ACTIVE_PCT_CMD",  20, 80),
    (61, "REACTIVE_PCT_CMD", 20, 80),
    (62, "PF_CMD",          900, 1000),
    (64, "CHG_POWER_PCT",   20, 80),
    (65, "DISCHG_POWER_PCT", 20, 80),
    (66, "ACCHG_POWER_PCT", 20, 80),
    (67, "ACCHG_SOC_LIMIT", 30, 80),
    (68, "ACCHG_START_0",   WIN_A, WIN_B),
    (69, "ACCHG_END_0",     WIN_A, WIN_B),
    (70, "ACCHG_START_1",   WIN_A, WIN_B),
    (71, "ACCHG_END_1",     WIN_A, WIN_B),
    (72, "ACCHG_START_2",   WIN_A, WIN_B),
    (73, "ACCHG_END_2",     WIN_A, WIN_B),
    (74, "CHGFIRST_POWER",  20, 80),
    (75, "CHGFIRST_SOC",    20, 90),
    (76, "CHGFIRST_START_0", WIN_A, WIN_B),
    (77, "CHGFIRST_END_0",  WIN_A, WIN_B),
    (82, "FDISCHG_POWER",   20, 80),
    (83, "FDISCHG_SOC",     30, 80),
    (84, "FDISCHG_START_0", WIN_A, WIN_B),
    (90, "EPS_VOLT_SET",    230, 240),
    (91, "EPS_FREQ_SET",    50, 60),
    (99, "CHARGE_VOLT_REF", 510, 560),
    (100, "CUT_VOLT_DISCHG", 420, 480),
    (101, "CHARGE_CURR",    20, 100),
    (102, "DISCHG_CURR",    20, 100),
    (103, "MAX_BACKFLOW",   10, 80),
    (105, "EOD",            20, 80),
    (110, "FUNCTION_EN1",   1, 8),
    (112, "SET_SYSTEM_TYPE", 0, 1),
    (113, "SET_COMPOSED_PH", 1, 3),
    (120, "SYS_ENABLE",     2, 8),
    (126, "OPTCHG_TABLE_0", 1, 2),
    (144, "FLOAT_CHARGE_VOLT", 510, 550),
    (145, "OUTPUT_PRIO_CFG", 0, 2),
    (146, "LINE_MODE",      0, 2),
    (147, "BAT_CAPACITY_AH", 100, 200),
    (148, "BAT_NOMINAL_VOLT", 420, 560),
    (152, "ACFIRST_START_0", WIN_A, WIN_B),
    (153, "ACFIRST_END_0",  WIN_A, WIN_B),
    (154, "ACFIRST_START_1", WIN_A, WIN_B),
    (155, "ACFIRST_END_1",  WIN_A, WIN_B),
    (156, "ACFIRST_START_2", WIN_A, WIN_B),
    (157, "ACFIRST_END_2",  WIN_A, WIN_B),
    (194, "GEN_CHG_START_V", 400, 450),  # both < end-V default (480): avoid the start<end clamp
    (195, "GEN_CHG_END_V",  500, 580),
    (196, "GEN_CHG_START_SOC", 10, 80),
    (197, "GEN_CHG_END_SOC", 30, 90),
    (198, "MAX_GEN_CHG_CURR", 10, 50),
]


def _fresh(image):
    be = FactoryBackend(image)
    if not be.available():
        raise SystemExit("factory backend unavailable (need unicorn + %s)" % image)
    return be


def capture(image, reg, val):
    """Fresh boot, single write of reg=val, build all blocks. Returns
    ({blk: payload-bytes}, stored?) -- stored is the dongle read-back."""
    be = _fresh(image)
    frames = be._blocks_after_write(reg, val)
    stored = be._boot()[1].read_holding(reg) == [val]
    return {b: bytes(frames[b][PAY_LO:PAY_HI]) for b in range(NBLOCKS)}, stored


def sweep(image):
    rows = []
    for reg, name, a, b in CANDIDATES:
        fa, sa = capture(image, reg, a)
        fb, sb = capture(image, reg, b)
        if not sa and not sb:
            # neither value stored: register inert/mode-gated in the default boot.
            rows.append((reg, name, "inert", [], []))
            continue
        if not (sa and sb):
            # only one value stored -> cannot differentiate live (e.g. HR 145 accepts
            # only its default here). Not proof of "no push"; left for static analysis.
            rows.append((reg, name, "1-value", [], []))
            continue
        fields, residue = [], []
        for blk in range(NBLOCKS):
            for i in range(PAY_HI - PAY_LO):
                if fa[blk][i] != fb[blk][i]:
                    off = PAY_LO + i
                    (residue if is_residue(blk, off) else fields).append((blk, off))
        rows.append((reg, name, "writable", sorted(set(fields)), sorted(set(residue))))
    return rows


def fmt_fields(fields):
    if not fields:
        return "none (ARM-local only)"
    # group consecutive offsets per block
    by = {}
    for blk, off in fields:
        by.setdefault(blk, []).append(off)
    parts = []
    for blk in sorted(by):
        offs = ", ".join("0x%02x" % o for o in by[blk])
        parts.append("block %d @ %s" % (blk, offs))
    return "; ".join(parts)


def main(argv):
    image = None
    md = None
    i = 0
    while i < len(argv):
        if argv[i] == "--md":
            md = argv[i + 1]; i += 2; continue
        image = argv[i]; i += 1
    image = image or os.environ.get("LXP_FACTORY_BIN") \
        or os.path.join(ROOT, "reference", "com_flat.bin")
    if not os.path.exists(image):
        image = os.path.join(ROOT, "reference", "ceaa-07xx_vE_260214.bin")
    rows = sweep(image)

    lines = []
    lines.append("# HR -> DSP push matrix (T25, factory %s)" % os.path.basename(image))
    lines.append("")
    lines.append("Each writable HR written at two distinct in-range values on separate")
    lines.append("fresh boots; a config-frame payload byte that differs between them is")
    lines.append("driven by that register. `inert` = a dongle write did not store.")
    lines.append("")
    lines.append("| HR | name | writable | pushed to | residue bytes |")
    lines.append("|---|---|---|---|---|")
    for reg, name, w, fields, residue in rows:
        res = "%d" % len(residue) if residue else "-"
        if w == "inert":
            pushed = "— (write did not store)"
        elif w == "1-value":
            pushed = "— (only one value stores; not exercisable live)"
        else:
            pushed = fmt_fields(fields)
        lines.append("| %d | %s | %s | %s | %s |" % (reg, name, w, pushed, res))
    out = "\n".join(lines) + "\n"
    if md:
        open(md, "w").write(out)
        print("wrote %s (%d registers)" % (md, len(rows)))
    else:
        print(out)
    # terse stderr summary
    pushed = [r for r in rows if r[3]]
    inert = [r for r in rows if r[2] == "inert"]
    sys.stderr.write("summary: %d regs, %d push to a block, %d inert\n"
                     % (len(rows), len(pushed), len(inert)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
