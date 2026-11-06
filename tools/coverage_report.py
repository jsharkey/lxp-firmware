#!/usr/bin/env python3
"""
coverage_report — turn an execution-coverage capture of the FACTORY image into
the checked-in dashboard docs/factory-coverage.md.

The idea (see docs/37-factory-coverage.md): `make test-sim` already runs the
proprietary factory image under the Unicorn harness (tools/arm_sim.py) so the
*same* black-box tests assert our reimplementation matches it. With
$LXP_COVERAGE set, the harness records the entry PC of every basic block the
factory image executes during those tests. This script maps those PCs onto the
recovered factory function map (reference/symbols.csv, 1083 functions) and asks:
of the factory functions we actually care about, how many did our parity tests
drive?

  numerator   = in-scope factory functions executed at least once
  denominator = all recovered functions, minus the ones we deliberately IGNORE
                (HMI rendering, C-runtime startup, …) — see the classification
                file (tests/factory_coverage_classify.csv).

A function is reported covered when any instruction inside it ran. We report a
plain function count AND an instruction-weighted figure (symbols.csv carries an
`insns` column) so a 4-instruction leaf doesn't count the same as a 360-insn
controller. Everything is derivable from committed, non-proprietary artifacts
(the symbol CSV + the classification CSV); only the *covered* set needs a run
against the proprietary image, so with no capture the dashboard still renders
the full in-scope surface as a worklist (0 covered) — honest, and useful.

What coverage does and does NOT mean is spelled out on the dashboard itself:
executing a factory function proves our tests *drove* it; the actual agreement
comes from the shared assertions, not this number. It measures breadth of
exercise, not depth of equivalence.

Usage:
    python3 tools/coverage_report.py \
        --cov build/factory_cov.jsonl \
        --symbols reference/symbols.csv \
        --classify tests/factory_coverage_classify.csv \
        --out docs/factory-coverage.md \
        [--image-name com_flat.bin] [--image-hash <sha256>]

Stdlib only (the sim suite prides itself on needing nothing but unicorn).
"""
import argparse, bisect, csv, datetime, os, sys
from collections import defaultdict

IGNORE, IN_SCOPE, UNREACHABLE, UNCLASSIFIED = (
    "ignore", "in_scope", "unreachable", "unclassified")
# A function's status decides which bucket it lands in. Only IGNORE and
# UNREACHABLE are removed from the denominator; UNCLASSIFIED stays IN it (so the
# headline can't be flattered by simply *not* triaging a hard function).
IN_DENOMINATOR = {IN_SCOPE, UNCLASSIFIED}


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
def load_functions(symbols_path):
    """reference/symbols.csv -> [{addr,name,insns}], sorted & de-duped by addr."""
    by_addr = {}
    with open(symbols_path) as f:
        for r in csv.DictReader(f):
            try:
                addr = int(r["addr"], 16)
            except (KeyError, ValueError):
                continue
            if addr in by_addr:
                continue  # first row wins (addresses are unique in practice)
            try:
                insns = int(r.get("insns") or 0)
            except ValueError:
                insns = 0
            by_addr[addr] = {"addr": addr, "name": r.get("name") or "sub_%08x" % addr,
                             "insns": insns}
    return [by_addr[a] for a in sorted(by_addr)]


def load_classification(path):
    """Classification rules. CSV columns: match,status,module,reason.

      match   0xADDR            one function by start address
              0xLO-0xHI         every function starting in [LO, HI]
              name:EXACT        every function with that exact recovered name
              name:PREFIX*      recovered name starts with PREFIX
      status  ignore | in_scope | unreachable      (default row = in_scope)
      module  free-text bucket for the per-module table (optional)
      reason  why (shown nowhere but kept for review — this file is the record)

    Returns a list of rules; apply_rules() resolves per function by specificity
    (address > name > range), ignore winning ties.
    """
    rules = []
    if not path or not os.path.exists(path):
        return rules
    with open(path) as f:
        # Drop comment/blank lines so the real `match,status,...` row is the
        # header DictReader keys on (it would otherwise key on a leading `#`).
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        for r in csv.DictReader(lines):
            match = (r.get("match") or "").strip()
            if not match or match.startswith("#"):
                continue
            status = (r.get("status") or IN_SCOPE).strip() or IN_SCOPE
            module = (r.get("module") or "").strip()
            if match.startswith("name:"):
                spec, key = 2, match[len("name:"):]
                kind = "name_prefix" if key.endswith("*") else "name"
                key = key[:-1] if kind == "name_prefix" else key
            elif "-" in match and match.lower().startswith("0x"):
                lo, hi = match.split("-", 1)
                spec, kind, key = 1, "range", (int(lo, 16), int(hi, 16))
            else:
                spec, kind, key = 3, "addr", int(match, 16)
            rules.append({"spec": spec, "kind": kind, "key": key,
                          "status": status, "module": module})
    return rules


def apply_rules(fn, rules):
    """Resolve (status, module) for one function. Most specific rule wins; on a
    tie an `ignore` outranks the rest (conservative: once excluded, excluded)."""
    best = None  # (spec, ignore_first, order)
    for i, rule in enumerate(rules):
        k = rule["kind"]
        hit = (
            (k == "addr" and fn["addr"] == rule["key"]) or
            (k == "range" and rule["key"][0] <= fn["addr"] <= rule["key"][1]) or
            (k == "name" and fn["name"] == rule["key"]) or
            (k == "name_prefix" and fn["name"].startswith(rule["key"]))
        )
        if not hit:
            continue
        rank = (rule["spec"], 1 if rule["status"] == IGNORE else 0, i)
        if best is None or rank > best[0]:
            best = (rank, rule)
    if best is None:
        return UNCLASSIFIED, ""
    return best[1]["status"], best[1]["module"]


def load_hmi_list(path):
    """reference/hmi_functions.csv (from tools/hmi_classify.py): candidate
    HMI-exclusive function start addresses. A SUPERSET — static call-graph
    closure over-approximates (a menu handler may also carry control logic), so
    the dashboard only actually ignores a listed function when the functional
    tests never execute it (see render)."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["addr"], 16)] = r.get("evidence") or "HMI (static closure)"
            except (KeyError, ValueError):
                pass
    return out


def load_coverage(path):
    """Executed PCs: a file of `0x........` lines (one per unique block entry;
    appended across the test processes make test-sim spawns). Missing/empty is a
    valid 'nothing measured yet' state."""
    pcs = set()
    if not path or not os.path.exists(path):
        return pcs, False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                pcs.add(int(line, 16))
            except ValueError:
                pass
    return pcs, True


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
def covered_functions(funcs, pcs):
    """Map each executed PC to the function whose [start, next_start) it falls in
    and return the set of covered function start addresses."""
    starts = [f["addr"] for f in funcs]
    hit = set()
    for pc in pcs:
        i = bisect.bisect_right(starts, pc) - 1
        if i < 0:
            continue
        lo = starts[i]
        hi = starts[i + 1] if i + 1 < len(starts) else lo + funcs[i]["insns"] * 4 + 4
        if lo <= pc < hi:
            hit.add(lo)
    return hit


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def bar(pct, width=28):
    filled = int(round(pct / 100.0 * width))
    return "█" * filled + "░" * (width - filled)


def pctof(n, d):
    return (100.0 * n / d) if d else 0.0


def render(funcs, rules, pcs, have_cov, image_name, image_hash, cov_path, hmi_list, note=""):
    covered = covered_functions(funcs, pcs)
    for fn in funcs:
        fn["covered"] = fn["addr"] in covered
    for fn in funcs:
        # Explicit classification wins absolutely (human decision). Otherwise an
        # HMI-list function is ignored ONLY if the functional tests never run it:
        # static closure over-approximates, so a listed function our tests DO
        # exercise (a settings handler that also drives config, say) stays in
        # scope and counts. This makes the ignore set shrink as the suite grows,
        # and the score can never be gamed by ignoring code we actually test.
        st, mod = apply_rules(fn, rules)
        if fn["addr"] in hmi_list:
            mod = mod or "hmi"
            if st == UNCLASSIFIED and not fn["covered"]:
                st = IGNORE
        fn["status"], fn["module"] = st, mod

    denom = [f for f in funcs if f["status"] in IN_DENOMINATOR]
    ignored = [f for f in funcs if f["status"] == IGNORE]
    unreach = [f for f in funcs if f["status"] == UNREACHABLE]
    unclass = [f for f in denom if f["status"] == UNCLASSIFIED]
    cov_d = [f for f in denom if f["covered"]]

    n_fns = pctof(len(cov_d), len(denom))
    di, ci = sum(f["insns"] for f in denom), sum(f["insns"] for f in cov_d)
    n_ins = pctof(ci, di)

    # covered-but-excluded: an exercised function we marked ignore/unreachable is
    # worth surfacing — 'unreachable' ones being hit means the label is wrong.
    cov_ignored = [f for f in ignored if f["covered"]]
    cov_unreach = [f for f in unreach if f["covered"]]

    L = []
    w = L.append
    w("# Factory firmware coverage")
    w("")
    w("_How much of the factory firmware our parity tests actually exercise._ "
      "Generated by `tools/coverage_report.py` — **do not edit by hand**; run "
      "`make coverage` (or `make test-sim` with a factory image).")
    w("")

    if not have_cov:
        w("> ⚠️ **No coverage capture recorded yet.** The figures below are the "
      "full in-scope factory surface with **0 measured** — a worklist, not a "
      "result. Run `make coverage` with the proprietary image available "
      "(`LXP_FACTORY_HEX=/path/to/vendor.hex make coverage`) to fill in the "
      "_covered_ column.")
        w("")

    w("## Headline")
    w("")
    w("| | covered | in scope | % |")
    w("|---|--:|--:|--:|")
    w("| **Functions** | %d | %d | **%.1f%%** |" % (len(cov_d), len(denom), n_fns))
    w("| **Instructions** (weighted) | %d | %d | **%.1f%%** |" % (ci, di, n_ins))
    w("")
    w("```")
    w("functions     %s %5.1f%%" % (bar(n_fns), n_fns))
    w("instructions  %s %5.1f%%" % (bar(n_ins), n_ins))
    w("```")
    w("")
    w("Denominator = **%d** recovered functions (`reference/symbols.csv`) minus "
      "**%d** ignored and **%d** marked unreachable-in-sim. Of the %d in scope, "
      "**%d are still unclassified** (not yet triaged — they count *against* the "
      "score until reviewed)." % (len(funcs), len(ignored), len(unreach),
                                   len(denom), len(unclass)))
    n_hmi_ign = sum(1 for f in ignored if f["module"] == "hmi")
    if n_hmi_ign:
        w("")
        w("Of the ignored, **%d are HMI-exclusive** (`reference/hmi_functions.csv`, "
          "from `tools/hmi_classify.py`) that the functional tests never execute. "
          "HMI-list functions the tests *do* execute stay in scope and count — so "
          "the ignore set shrinks as the suite grows." % n_hmi_ign)
    w("")

    # per-module ---------------------------------------------------------
    w("## By module")
    w("")
    w("In-scope functions grouped by `module` (from "
      "`tests/factory_coverage_classify.csv`, plus `hmi` for functions on the "
      "HMI list the tests still exercise). Untagged functions fall in "
      "_(untagged)_ — tag them to sharpen this table.")
    w("")
    w("| module | covered | funcs | % | insns % |")
    w("|---|--:|--:|--:|--:|")
    bym = defaultdict(list)
    for f in denom:
        bym[f["module"] or "(untagged)"].append(f)
    def modkey(item):
        name, fns = item
        return (-pctof(sum(f["covered"] for f in fns), len(fns)), name)
    for name, fns in sorted(bym.items(), key=modkey):
        cv = [f for f in fns if f["covered"]]
        di_m = sum(f["insns"] for f in fns)
        ci_m = sum(f["insns"] for f in cv)
        w("| %s | %d | %d | %.1f%% | %.1f%% |" % (
            name, len(cv), len(fns), pctof(len(cv), len(fns)), pctof(ci_m, di_m)))
    w("")

    # worklist -----------------------------------------------------------
    TOP = 40
    uncov = sorted((f for f in denom if not f["covered"]),
                   key=lambda f: (-f["insns"], f["addr"]))
    w("## Worklist — biggest unexercised in-scope functions")
    w("")
    w("The fattest factory behaviour no parity test drives yet, by instruction "
      "count. This is the to-do list: pick one, write a black-box `test-sim` "
      "case that drives it on both images.")
    w("")
    w("| # | addr | name | insns | module | status |")
    w("|--:|---|---|--:|---|---|")
    for i, f in enumerate(uncov[:TOP], 1):
        w("| %d | `0x%08x` | `%s` | %d | %s | %s |" % (
            i, f["addr"], f["name"], f["insns"], f["module"] or "—", f["status"]))
    if len(uncov) > TOP:
        w("")
        w("_…and %d more unexercised in-scope functions._" % (len(uncov) - TOP))
    w("")

    # anomalies ----------------------------------------------------------
    if cov_unreach or cov_ignored:
        w("## Notes")
        w("")
        if cov_unreach:
            w("- ⚠️ **%d function(s) marked `unreachable` were executed** — the "
              "label is wrong; re-triage: %s" % (
                  len(cov_unreach),
                  ", ".join("`0x%08x`" % f["addr"] for f in cov_unreach[:12])))
        if cov_ignored:
            w("- %d ignored function(s) were executed (expected — ignored code "
              "still runs; it just doesn't count)." % len(cov_ignored))
        w("")

    # provenance ---------------------------------------------------------
    w("---")
    w("")
    w("### What this does and does not prove")
    w("")
    w("- **Covered ≠ correct.** Executing a factory function proves a test "
      "*drove* it; agreement comes from the shared assertions in that test, not "
      "from this number. Coverage is breadth of exercise, not depth of "
      "equivalence.")
    w("- **Function-hit is an upper bound on confidence.** A function entered on "
      "one trivial input counts covered even if its fault/edge branches never "
      "run.")
    w("- **The denominator is the _recovered_ map** (`recurse.py`, ~72% of the "
      "image is code; boundaries are heuristic), not every function that exists.")
    w("")
    src = image_name or (os.path.basename(cov_path) if cov_path else "—")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    prov = "Generated %s · image `%s`" % (stamp, src)
    if image_hash:
        prov += " · sha256 `%s`" % image_hash[:16]
    prov += " · %d functions in map" % len(funcs)
    if not have_cov:
        prov += " · **no capture**"
    w("_%s_" % prov)
    if note:
        w("")
        w("_%s_" % note)
    w("")
    return "\n".join(L)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cov", default="build/factory_cov.jsonl")
    ap.add_argument("--symbols", default="reference/symbols.csv")
    ap.add_argument("--classify", default="tests/factory_coverage_classify.csv")
    ap.add_argument("--hmi-list", default="reference/hmi_functions.csv")
    ap.add_argument("--out", default="docs/factory-coverage.md")
    ap.add_argument("--image-name", default="")
    ap.add_argument("--image-hash", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv[1:])

    if not os.path.exists(a.symbols):
        sys.stderr.write("coverage_report: no symbol map at %s\n" % a.symbols)
        return 2
    funcs = load_functions(a.symbols)
    rules = load_classification(a.classify)
    hmi_list = load_hmi_list(a.hmi_list)
    pcs, have_cov = load_coverage(a.cov)
    md = render(funcs, rules, pcs, have_cov, a.image_name, a.image_hash, a.cov,
                hmi_list, a.note)
    with open(a.out, "w") as f:
        f.write(md)
    covered = sum(1 for f in funcs
                  if f.get("status") in IN_DENOMINATOR and f.get("covered"))
    denom = sum(1 for f in funcs if f.get("status") in IN_DENOMINATOR)
    sys.stderr.write("coverage_report: wrote %s — %d/%d in-scope functions%s\n" % (
        a.out, covered, denom, "" if have_cov else " (no capture; worklist only)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
