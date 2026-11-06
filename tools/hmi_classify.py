#!/usr/bin/env python3
"""
hmi_classify — find the factory firmware's HMI-exclusive functions so the
coverage dashboard (docs/36) can ignore them.

We reimplement the HMI our own way (docs/06, docs/27, docs/28), so the factory's
menu/display code is out of scope for the parity metric. This tool identifies it
statically and emits reference/hmi_functions.csv (addresses + evidence, like the
other derived maps — the proprietary image itself never enters the tree).

Method — call-graph closure, barriered against control:

  roots (HMI)   functions whose literal pool references the on-screen string
                data (0x…55b6–0x…f7f5) or one of the menu string-pointer TABLES
                (the 93-entry settings menu @0x08005fec et al.), PLUS the menu
                handlers docs/03 named from their on-screen text.
  HMI_set       everything reachable from those roots (they call the formatters
                and the bit-banged LCD panel driver, docs/28 — all display code).
  CONTROL_set   everything reachable from the real entry points (Reset + the
                ISR/exception vectors) WITH the HMI roots deleted from the graph,
                so a utility shared with control code (reached without going
                through an HMI root) stays protected.
  ignore        HMI_set − CONTROL_set.

A function shared by both (e.g. a CRC or fixed-point helper the control path also
calls) is reachable from control without an HMI root, so it is NOT ignored. A
function the control path only ever reaches to paint a screen IS ignored. The
call graph (reference/callgraph.txt) already includes indirect calls resolved
from literal pools (docs/03), so RTOS task pointers and the like are edges too.

Approximations (documented so the next agent can tighten them): recovered
function boundaries are heuristic; a handful of curated names are non-unique
(fn_ceaa at several addresses) and get every address; literal-pool scanning is a
superset of a function's true constants. The output is therefore a reviewed
candidate list — the coverage dashboard also flags any ignored function that the
functional tests actually execute (covered-but-ignored), as a standing check.

Usage:
    python3 tools/hmi_classify.py \
        --image reference/com_flat.bin \
        --symbols reference/symbols.csv \
        --callgraph reference/callgraph.txt \
        --out reference/hmi_functions.csv

Needs the factory image present (built via `make factory`). Stdlib only.
"""
import argparse, csv, os, struct, sys
from collections import defaultdict, deque

BASE = 0x08000000

# Menu handlers docs/03 named from their on-screen text — seeded as HMI roots in
# case the literal scan misses one (closure then pulls in their subtrees).
NAMED_HMI_ROOTS = {
    "fn_Hybrid_Setting", "fn_Parallel_Setting", "fn_Smart_Load", "fn_AC_Couple",
    "fn_NO_Fault", "fn_NO_Alarm", "fn_download", "fn_Meter",
    "fn_Lead_Acid_Floating_Voltage", "fn_AC_Charge_Battery_Voltage",
    "fn_Warning", "fn_YES", "fn_Next_there_will_be_four_display",
}
# Real entry points: reset + CPU/peripheral vectors. Control reachability starts
# here. (Names as spelled in symbols.csv.)
CONTROL_ROOT_SUFFIX = "_Handler"
CONTROL_ROOT_NAMES = {"Reset_Handler"}


def load_funcs(path):
    funcs = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                addr = int(r["addr"], 16)
            except (KeyError, ValueError):
                continue
            try:
                insns = int(r.get("insns") or 0)
            except ValueError:
                insns = 0
            funcs.append({"addr": addr, "name": r.get("name") or "sub_%08x" % addr,
                          "insns": insns})
    funcs.sort(key=lambda f: f["addr"])
    # de-dup addresses, first wins
    seen, out = set(), []
    for f in funcs:
        if f["addr"] in seen:
            continue
        seen.add(f["addr"])
        out.append(f)
    return out


def string_region_and_tables(data):
    """Return (set_of_string_start_addrs, [(table_lo, table_hi)]). A table is a
    run of >=3 consecutive 4-byte words each pointing at a string start."""
    N = len(data)
    starts = set()
    i = 0
    while i < N:
        if 32 <= data[i] < 127:
            j = i
            while j < N and 32 <= data[j] < 127:
                j += 1
            if j - i >= 4 and j < N and data[j] == 0:
                starts.add(BASE + i)
            i = j
        else:
            i += 1
    lo, hi = (min(starts), max(starts)) if starts else (0, 0)
    tables, run = [], []
    for o in range(0, N - 3, 4):
        w = struct.unpack_from("<I", data, o)[0]
        if w in starts:
            run.append(BASE + o)
        else:
            if len(run) >= 3:
                tables.append((run[0], run[-1] + 4))
            run = []
    if len(run) >= 3:
        tables.append((run[0], run[-1] + 4))
    return starts, (lo, hi), tables


def func_ranges(funcs):
    """[(lo, hi, fn)] covering each function up to the next function start."""
    out = []
    for i, f in enumerate(funcs):
        hi = funcs[i + 1]["addr"] if i + 1 < len(funcs) else f["addr"] + f["insns"] * 4 + 8
        out.append((f["addr"], hi, f))
    return out


def find_string_roots(data, funcs, strstarts, tables):
    """Functions whose literal pool references string data or a menu table."""
    N = len(data)
    in_table = lambda w: any(lo <= w < hi for lo, hi in tables)
    roots = {}
    for lo, hi, fn in func_ranges(funcs):
        o = lo - BASE
        end = min(hi - BASE, N)
        why = None
        oo = o - (o % 4)
        while oo + 4 <= end:
            w = struct.unpack_from("<I", data, oo)[0]
            if w in strstarts:
                why = "refs string data"
                break
            if in_table(w):
                why = "refs menu table 0x%08x" % w
                break
            oo += 4
        if why:
            roots[fn["addr"]] = why
    return roots


def build_graph(callgraph_path, funcs):
    """caller_addr -> set(callee_addr), resolving names. sub_HEX encodes its own
    address; a curated name maps to every address that carries it."""
    name2addrs = defaultdict(list)
    for f in funcs:
        name2addrs[f["name"]].append(f["addr"])

    def resolve(name):
        if name in name2addrs:
            return name2addrs[name]
        if name.startswith("sub_"):
            try:
                return [int(name[4:], 16)]
            except ValueError:
                return []
        return []

    edges = defaultdict(set)
    with open(callgraph_path) as f:
        for line in f:
            if "->" not in line:
                continue
            a, b = (s.strip() for s in line.split("->", 1))
            for ca in resolve(a):
                for cb in resolve(b):
                    edges[ca].add(cb)
    return edges


def closure(roots, edges, barriers=frozenset()):
    """Forward reachability from roots; `barriers` nodes are deleted (not entered
    and not included, unless they are themselves roots)."""
    seen, q = set(), deque()
    for r in roots:
        if r in barriers:
            continue
        if r not in seen:
            seen.add(r)
            q.append(r)
    while q:
        n = q.popleft()
        for m in edges.get(n, ()):
            if m in barriers or m in seen:
                continue
            seen.add(m)
            q.append(m)
    return seen


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", default="reference/com_flat.bin")
    ap.add_argument("--symbols", default="reference/symbols.csv")
    ap.add_argument("--callgraph", default="reference/callgraph.txt")
    ap.add_argument("--out", default="reference/hmi_functions.csv")
    a = ap.parse_args(argv[1:])

    if not os.path.exists(a.image):
        sys.stderr.write(
            "hmi_classify: need the factory image at %s (run `make factory` "
            "with LXP_FACTORY_HEX=...). Nothing written.\n" % a.image)
        return 2
    data = open(a.image, "rb").read()
    funcs = load_funcs(a.symbols)
    by_addr = {f["addr"]: f for f in funcs}

    strstarts, (slo, shi), tables = string_region_and_tables(data)
    str_roots = find_string_roots(data, funcs, strstarts, tables)
    named_roots = {f["addr"]: "menu handler %s (docs/03)" % f["name"]
                   for f in funcs if f["name"] in NAMED_HMI_ROOTS}
    hmi_roots = dict(str_roots)
    for k, v in named_roots.items():
        hmi_roots.setdefault(k, v)

    control_roots = [f["addr"] for f in funcs
                     if f["name"] in CONTROL_ROOT_NAMES
                     or f["name"].endswith(CONTROL_ROOT_SUFFIX)]

    edges = build_graph(a.callgraph, funcs)
    hmi_set = closure(hmi_roots.keys(), edges)
    control_set = closure(control_roots, edges, barriers=set(hmi_roots.keys()))
    ignore = sorted(hmi_set - control_set)

    ins = sum(by_addr[x]["insns"] for x in ignore if x in by_addr)
    with open(a.out, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["addr", "name", "insns", "evidence"])
        for x in ignore:
            fn = by_addr.get(x)
            if not fn:
                continue
            if x in hmi_roots:
                why = hmi_roots[x]
            else:
                why = "reached only from HMI (call-graph closure)"
            w.writerow(["0x%08x" % x, fn["name"], fn["insns"], why])

    sys.stderr.write(
        "hmi_classify: %d HMI roots (%d by string/menu ref, %d named) -> "
        "%d HMI-exclusive functions (%d insns) written to %s\n" % (
            len(hmi_roots), len(str_roots), len(named_roots),
            len(ignore), ins, a.out))
    sys.stderr.write(
        "hmi_classify: string data 0x%08x..0x%08x, %d menu tables\n" % (
            slo, shi, len(tables)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
