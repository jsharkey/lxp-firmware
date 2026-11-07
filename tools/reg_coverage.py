#!/usr/bin/env python3
"""
Register-coverage bookkeeping for the dongle Modbus map (docs/39 T22).

Read-only. Cross-references three things:
  1. the register map          -- include/inv/modbus_map.h (IR_* / HR_* enums)
  2. what the tests cover       -- the shared contract tables (authoritative) plus
                                   an IR_*/HR_* symbol scan of tests/
  3. what each register's doc claims -- the `## Test coverage` section of every
                                   docs/wiring/ARM-UART5-dongle/<range>.md file

and reports:
  A. docs that UNDER-RECORD a test that already covers their register (the
     catch-up list -- these doc sections lag the suite);
  B. spec registers with NO test at all (the honest gap list).

Nothing is executed and no firmware image is needed; it only reads source.

Usage:
  python3 tools/reg_coverage.py              # summary + catch-up (A) + gaps (B)
  python3 tools/reg_coverage.py --matrix     # also the full register x test matrix
  python3 tools/reg_coverage.py --check      # exit 1 if any doc under-records (CI)
Or:  make coverage-report
"""
import os, re, sys, importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
DOCS = os.path.join(ROOT, "docs", "wiring", "ARM-UART5-dongle")
MAP_H = os.path.join(ROOT, "include", "inv", "modbus_map.h")
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(ROOT, "tools"))


# ---- 1. the register map (modbus_map.h IR_* / HR_* enums) -------------------
def parse_map():
    """Return (ir_num2sym, hr_num2sym): {number: SYMBOL} for each space."""
    txt = open(MAP_H).read()
    ir, hr = {}, {}
    for m in re.finditer(r"\b(IR|HR)_([A-Z0-9_]+)\s*=\s*(\d+)", txt):
        space, name, num = m.group(1), m.group(2), int(m.group(3))
        (ir if space == "IR" else hr)["%s_%s" % (space, name)] = num
    ir_n2s, hr_n2s = {}, {}
    for s, n in ir.items():
        ir_n2s.setdefault(n, s)
    for s, n in hr.items():
        hr_n2s.setdefault(n, s)
    return ir_n2s, hr_n2s


# ---- 3. doc files: owning range + the `## Test coverage` section ------------
DOC_RE = re.compile(r"^(IR|HR)(\d+)(?:_(\d+))?-")


def parse_docs():
    """Return (owner, coverage_text):
       owner[(space, num)] = filename   -- which doc owns each register
       coverage_text[filename] = the text of its `## Test coverage` section."""
    owner, coverage = {}, {}
    for fn in sorted(os.listdir(DOCS)):
        m = DOC_RE.match(fn)
        if not m:
            continue
        space, start = m.group(1), int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        for n in range(start, end + 1):
            owner[(space, n)] = fn
        txt = open(os.path.join(DOCS, fn)).read()
        cov = ""
        mcov = re.search(r"##\s*Test coverage\s*(.*?)(?:\n##\s|\Z)", txt, re.S)
        if mcov:
            cov = mcov.group(1)
        coverage[fn] = cov
    return owner, coverage


# ---- 2a. authoritative coverage from the shared contract tables -------------
# Each entry: (label, space, regs, doc_tokens) -- doc_tokens are strings a doc's
# Test coverage section must contain to count as "records this test".
def table_coverage():
    entries = []

    def add(label, space, regs, tokens):
        regs = {int(r) for r in regs if r is not None}
        if regs:
            entries.append((label, space, regs, tokens))

    def imp(mod):
        try:
            return importlib.import_module(mod)
        except Exception as e:                       # pragma: no cover
            sys.stderr.write("warn: could not import %s (%s)\n" % (mod, e))
            return None

    m = imp("settings_persist_contract")
    if m:
        add("persistence (T03, cross-image)", "HR", [r[0] for r in m.SETTINGS_MAP],
            ["test_persist_crossimage", "settings_persist_contract"])
    m = imp("settings_contract")
    if m:
        add("write-semantics (T04)", "HR", [v[1] for v in m.WRITE_VECTORS],
            ["settings_contract", "test_settings_validate", "settings_validate"])
    m = imp("arm_sim_contract")
    if m:
        add("safety-CPU telemetry (T02a/T05)", "IR",
            [v[1] for v in m.SAFETY_TELEMETRY.values()],
            ["SAFETY_TELEMETRY", "safety_cpu_telemetry", "arm_sim_contract",
             "usart2_frame_reaches_modbus"])
    m = imp("telemetry_contract")
    if m:
        regs = set(m.SERVE_EXPECTED) | set(getattr(m, "OURS_EXTRA", {})) | set(getattr(m, "FACTORY_SRC", {}))
        add("ARM telemetry serve (T07)", "IR", regs,
            ["telemetry_contract", "test_telemetry"])
    m = imp("energy_contract")
    if m:
        # the counters the energy tests actually drive/read (Epv1 day + all)
        add("energy counters (T07/energy)", "IR", [28, 40, 41],
            ["test_energy", "energy_contract"])
    m = imp("dsppush_contract")
    if m:
        add("DSP config-push (T10)", "HR",
            [r for r, v in m.DSP_PUSH.items() if v is not None],
            ["test_dsp_push", "dsppush_contract"])
        if hasattr(m, "GRID_PUSH"):
            add("DSP grid-charge slot fields (T10)", "HR", list(m.GRID_PUSH),
                ["test_dsp_push", "dsppush_contract"])
    return entries


# ---- 2b. supplementary: IR_*/HR_* symbol scan of tests/ ---------------------
_READ_RE = re.compile(r"\b(read_input|read_holding)\s*\(\s*(\d+)\s*(?:,\s*(\d+))?")
_WRITE_RE = re.compile(r"\bwrite_single\s*\(\s*(\d+)")


def symbol_scan(ir_n2s, hr_n2s):
    """{(space, num): set("sym:file"|"read:file")} -- every register a test
    *touches*: by IR_*/HR_* symbol (any test), or by a numeric dongle
    read_input/read_holding/write_single call (the black-box sim tests, which
    reference registers by number, not symbol). A block read read_input(S, C)
    touches S..S+C-1. 'Touch' = read/write/assert, the universe for the gap list;
    whether a touched register is *asserted* is what its doc records (section A)."""
    sym2 = {}
    for n, s in ir_n2s.items():
        sym2[s] = ("IR", n)
    for n, s in hr_n2s.items():
        sym2[s] = ("HR", n)
    touched = {}
    for fn in sorted(os.listdir(TESTS)):
        if not (fn.endswith(".py") or fn.endswith(".c")):
            continue
        txt = open(os.path.join(TESTS, fn)).read()
        for sym in set(re.findall(r"\b([IH]R_[A-Z0-9_]+)\b", txt)):
            if sym in sym2:
                touched.setdefault(sym2[sym], set()).add("sym:%s" % fn)
        if fn.endswith(".py"):
            for m in _READ_RE.finditer(txt):
                space = "IR" if m.group(1) == "read_input" else "HR"
                start = int(m.group(2)); count = int(m.group(3)) if m.group(3) else 1
                for n in range(start, start + count):
                    touched.setdefault((space, n), set()).add("read:%s" % fn)
            for m in _WRITE_RE.finditer(txt):
                touched.setdefault(("HR", int(m.group(1))), set()).add("read:%s" % fn)
    return touched


def main(argv):
    want_matrix = "--matrix" in argv
    check = "--check" in argv
    ir_n2s, hr_n2s = parse_map()
    owner, coverage = parse_docs()
    tables = table_coverage()
    scanned = symbol_scan(ir_n2s, hr_n2s)

    # actual coverage: (space, num) -> set(labels)
    tested = {}
    for label, space, regs, _tok in tables:
        for n in regs:
            tested.setdefault((space, n), set()).add(label)
    for key, files in scanned.items():
        for f in files:
            tested.setdefault(key, set()).add("symbol:%s" % f)

    # A. doc under-records a covering test
    lag = []   # (space, num, doc, label, tokens)
    for label, space, regs, tokens in tables:
        for n in sorted(regs):
            doc = owner.get((space, n))
            if not doc:
                continue                       # no doc file owns it (reported in B/own line)
            cov = coverage.get(doc, "")
            if not any(t in cov for t in tokens):
                lag.append((space, n, doc, label, tokens))

    # B. spec registers (named enum members) with no test at all
    gaps = []
    for n2s, space in ((ir_n2s, "IR"), (hr_n2s, "HR")):
        for num, sym in sorted(n2s.items()):
            if (space, num) not in tested:
                gaps.append((space, num, sym, owner.get((space, num), "-")))

    # file-level: how many register docs still record no test in their section
    reg_docs = [f for f in coverage if DOC_RE.match(f)]
    docs_no_test = sorted(f for f in reg_docs
                          if not re.search(r"test_\w|\.py\b|\.c\b", coverage[f]))

    # ---- check mode: quiet unless something is wrong ----
    if check:
        if lag:
            print("reg_coverage --check FAIL: %d register(s) are covered by a test "
                  "their doc's `## Test coverage` does not record:" % len(lag))
            bydoc = {}
            for space, num, doc, label, _tok in lag:
                bydoc.setdefault(doc, []).append("%s%d" % (space, num))
            for doc in sorted(bydoc):
                print("  %-36s %s" % (doc, ", ".join(bydoc[doc])))
            print("  -> run `make coverage-report` and update those docs.")
            return 1
        print("reg_coverage --check OK: every covering test is recorded in its register's doc.")
        return 0

    # ---- report ----
    n_ir, n_hr = len(ir_n2s), len(hr_n2s)
    n_tested = len(tested)
    print("# Register coverage (read-only; docs/39 T22)")
    print("map: %d IR + %d HR named registers; %d register-slots have >=1 test"
          % (n_ir, n_hr, n_tested))
    print("register docs: %d of %d name no test in their `## Test coverage` section"
          % (len(docs_no_test), len(reg_docs)))
    print()

    print("## A. Docs that under-record an existing test  (%d) -- catch-up" % len(lag))
    bydoc = {}
    for space, num, doc, label, _tok in lag:
        bydoc.setdefault(doc, []).append((space, num, label))
    for doc in sorted(bydoc):
        rows = bydoc[doc]
        regs = ", ".join("%s%d" % (s, n) for s, n, _l in rows)
        labels = sorted({l for _s, _n, l in rows})
        print("  %-36s  %s" % (doc, "; ".join(labels)))
        print("        regs: %s" % regs)
    if not lag:
        print("  (none -- every covering test is recorded in its register's doc)")
    print()

    print("## B. Spec registers with NO test at all  (%d)" % len(gaps))
    cur = None
    line = []
    for space, num, sym, doc in gaps:
        if space != cur:
            if line:
                print("  %s: %s" % (cur, ", ".join(line)))
            cur, line = space, []
        line.append("%d(%s)" % (num, doc if doc != "-" else "no-doc"))
    if line:
        print("  %s: %s" % (cur, ", ".join(line)))
    if not gaps:
        print("  (none)")
    print()

    if want_matrix:
        print("## Register x test matrix")
        for n2s, space in ((ir_n2s, "IR"), (hr_n2s, "HR")):
            for num, sym in sorted(n2s.items()):
                labels = sorted(tested.get((space, num), []))
                print("  %-4s %-22s %-28s %s"
                      % ("%s%d" % (space, num), sym, owner.get((space, num), "-"),
                         ", ".join(labels) if labels else "-- no test --"))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
