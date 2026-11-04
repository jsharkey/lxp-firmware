#!/usr/bin/env python3
"""
Tiny shared runner for the arm_sim test files -- pretty output, zero extra
dependencies (so `make test-sim` still needs only unicorn, never pytest).

Each test file collects its own `test_*` functions and calls run_tests() with a
title + the image under test; this prints a banner header (with newlines around
it) naming the block, then a colour/emoji-tagged line per result, then a
one-line summary, and returns a process exit code (non-zero iff something
failed or errored). A test may raise `Skip` to report itself skipped.

Output adapts to the destination: colour + emoji when stdout is a terminal,
plain `PASS/FAIL/SKIP/ERROR` lines when piped or in CI logs (and whenever
$NO_COLOR is set), so logs stay clean and greppable. $FORCE_COLOR forces the
pretty form.
"""
import os, sys


class Skip(Exception):
    """Raised by a test to report itself skipped (e.g. image not available)."""
    pass


def _pretty():
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def run_tests(title, image, namespace):
    """Run every `test_*` in `namespace` (a module's globals()). `title` names
    the block; `image` is the firmware path under test (shown in the header)."""
    pretty = _pretty()

    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if pretty else s

    # result kind -> (emoji, plain label, colour)
    TAGS = {
        "pass":  ("✅", "PASS ", "32"),        # white check mark
        "skip":  ("⏭️", "SKIP ", "33"),  # next-track button
        "fail":  ("❌", "FAIL ", "31"),        # cross mark
        "error": ("\U0001f4a5", "ERROR", "31"),    # collision
    }

    def tag(kind):
        emoji, label, col = TAGS[kind]
        return ("%s %s" % (emoji, c(col, label))) if pretty else label.strip()

    # --- header banner (a single rule + title line delimits the block) -----
    bar = "═" * 64 if pretty else "=" * 64
    head = "%s  ·  image = %s" % (title, image) if pretty \
        else "%s  (image = %s)" % (title, image)
    print(c("1;36", bar))
    print(c("1;36", "  " + head))

    tests = [v for k, v in sorted(namespace.items())
             if k.startswith("test_") and callable(v)]
    n = {"pass": 0, "skip": 0, "fail": 0, "error": 0}
    for t in tests:
        name = t.__name__
        try:
            t()
            n["pass"] += 1
            print("  %s  %s" % (tag("pass"), name))
        except Skip as s:
            n["skip"] += 1
            print("  %s  %s  %s" % (tag("skip"), name, c("2", "(%s)" % s)))
        except AssertionError as a:
            n["fail"] += 1
            print("  %s  %s\n        %s" % (tag("fail"), name, a))
        except Exception as e:  # noqa: BLE001 -- a test crashing is a failure
            n["error"] += 1
            print("  %s  %s\n        %r" % (tag("error"), name, e))

    # --- summary -----------------------------------------------------------
    parts = [c("32", "%d passed" % n["pass"])]
    if n["fail"]:
        parts.append(c("31", "%d failed" % n["fail"]))
    if n["error"]:
        parts.append(c("31", "%d error" % n["error"]))
    if n["skip"]:
        parts.append(c("33", "%d skipped" % n["skip"]))
    print("  " + c("1", "→ ") + ", ".join(parts))
    print()   # one trailing blank line separates this block from the next
    return 1 if (n["fail"] or n["error"]) else 0
