"""Shared contract for the focused time-window micro-tests (docs/35).

The expensive full-simulator suite (tests/test_arm_sim.py) boots an entire
firmware image and talks Modbus to reach the AC-First status bit. That is
valuable but slow, and it gets slower as the harness grows. This module backs a
*narrow* alternative: exercise ONLY the "is the clock inside an AC-First window
now?" logic, two ways, against ONE set of vectors:

  * OursBackend    -- calls our compiled pure function acfirst_window_active()
                      (src/sched/acfirst.c) via ctypes. No emulator, no ARM
                      toolchain: the same host `cc` that `make test` already uses.
  * FactoryBackend -- calls just the factory ARM evaluator in Unicorn, with only
                      the RTC + window registers seeded (no boot). This is the
                      same isolated-call recipe as tools/emu_acfirst.py, reduced
                      to a function. Needs `pip install unicorn` and a factory
                      image; skips cleanly without them.

The test body (tests/test_timewindow.py) is identical for both backends -- it
asserts each VECTOR against whichever backend, and (when both are available)
that the factory oracle and our firmware AGREE on every vector. Same test code,
factory-vs-ours, at a fraction of the full-sim cost.

Extending to the other time-window features (charge/discharge schedule HR64-89,
OptimalChg HR126-131): give our firmware a pure evaluator the same shape as
acfirst_window_active(), add its vectors here, and point a FactoryBackend
profile at the corresponding factory evaluator. See docs/35.
"""
import contextlib
import io
import os
import struct
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def now_minutes(hour, minute):
    """Minutes-of-day, matching acfirst_reg_minutes()/the factory `60*hour+min`."""
    return 60 * hour + minute


def pack_window(hour, minute):
    """A window register as Modbus/firmware carry it: u16 = (minute<<8)|hour."""
    return ((minute & 0xFF) << 8) | (hour & 0xFF)


def W(hs, ms, he, me):
    """A {start,end} window pair (two packed regs)."""
    return (pack_window(hs, ms), pack_window(he, me))


_EMPTY = (0, 0)


def slot(win, idx):
    """Three-window config with `win` in slot `idx` (0..2), others empty."""
    w = [_EMPTY, _EMPTY, _EMPTY]
    w[idx] = win
    return tuple(w)


# --- the shared vectors -----------------------------------------------------
# Each: (name, windows, hour, minute, expected_active). `windows` is always three
# {start,end} pairs (6 packed regs) to match HR 152-157 / ACFIRST_NUM_WINDOWS --
# the factory evaluator sub_080352d0 reads all three (proven: it reads config
# +0x64/+0x66, +0x68/+0x6a, +0x6c/+0x6e). Spec: start-inclusive, end-exclusive,
# midnight wrap when start > end, empty window (start == end) never active, OR
# across the three windows. Every vector is checked against BOTH our firmware and
# the factory evaluator, and they are asserted to agree.
_W_6_8 = W(6, 0, 8, 0)      # 06:00-08:00

VECTORS = [
    # --- single daytime window 06:00-08:00, edge behaviour -----------------
    ("05:59 off (before start)",     slot(_W_6_8, 0), 5, 59, False),
    ("06:00 active (start incl.)",   slot(_W_6_8, 0), 6,  0, True),
    ("07:30 active",                 slot(_W_6_8, 0), 7, 30, True),
    ("07:59 active",                 slot(_W_6_8, 0), 7, 59, True),
    ("08:00 off (end excl.)",        slot(_W_6_8, 0), 8,  0, False),
    ("09:00 off (after end)",        slot(_W_6_8, 0), 9,  0, False),

    # --- all three window slots are honoured (same window, each slot) ------
    ("06-08 in slot 0 @07:00 on",    slot(_W_6_8, 0), 7, 0, True),
    ("06-08 in slot 1 @07:00 on",    slot(_W_6_8, 1), 7, 0, True),
    ("06-08 in slot 2 @07:00 on",    slot(_W_6_8, 2), 7, 0, True),

    # --- three distinct windows configured at once -------------------------
    # w0 02:00-04:00, w1 10:00-11:00, w2 20:00-22:00
    ("3wins @03:00 -> w0",   (W(2,0,4,0), W(10,0,11,0), W(20,0,22,0)), 3, 0, True),
    ("3wins @10:30 -> w1",   (W(2,0,4,0), W(10,0,11,0), W(20,0,22,0)), 10, 30, True),
    ("3wins @21:00 -> w2",   (W(2,0,4,0), W(10,0,11,0), W(20,0,22,0)), 21, 0, True),
    ("3wins @05:00 -> gap",  (W(2,0,4,0), W(10,0,11,0), W(20,0,22,0)), 5, 0, False),
    ("3wins @12:00 -> gap",  (W(2,0,4,0), W(10,0,11,0), W(20,0,22,0)), 12, 0, False),

    # --- overlapping windows: OR semantics ---------------------------------
    # w0 06:00-08:00, w1 07:00-09:00 (overlap 07:00-08:00)
    ("overlap @07:30 (both)", (W(6,0,8,0), W(7,0,9,0), _EMPTY), 7, 30, True),
    ("overlap @08:30 (w1)",   (W(6,0,8,0), W(7,0,9,0), _EMPTY), 8, 30, True),
    ("overlap @05:30 (none)", (W(6,0,8,0), W(7,0,9,0), _EMPTY), 5, 30, False),

    # --- empty / disabled windows ------------------------------------------
    ("empty window never active",   slot(W(3, 0, 3, 0), 0), 3, 0, False),
    ("00:00-00:00 empty @12:00",    slot(W(0, 0, 0, 0), 0), 12, 0, False),
    ("all-empty off",               (_EMPTY, _EMPTY, _EMPTY), 10, 0, False),

    # --- midnight edge conditions ------------------------------------------
    # window that STARTS at midnight: 00:00-06:00 (normal, start=0)
    ("00:00-06:00 @00:00 on (start incl.)", slot(W(0,0,6,0), 0), 0, 0, True),
    ("00:00-06:00 @05:59 on",               slot(W(0,0,6,0), 0), 5, 59, True),
    ("00:00-06:00 @06:00 off (end excl.)",  slot(W(0,0,6,0), 0), 6, 0, False),
    ("00:00-06:00 @23:59 off",              slot(W(0,0,6,0), 0), 23, 59, False),

    # window that ENDS at midnight: 18:00-00:00 (end packs to 0x0000, start>end
    # -> wrap branch; active 18:00..23:59, OFF exactly at 00:00)
    ("18:00-00:00 @18:00 on",               slot(W(18,0,0,0), 0), 18, 0, True),
    ("18:00-00:00 @23:59 on",               slot(W(18,0,0,0), 0), 23, 59, True),
    ("18:00-00:00 @00:00 off",              slot(W(18,0,0,0), 0), 0, 0, False),
    ("18:00-00:00 @17:59 off",              slot(W(18,0,0,0), 0), 17, 59, False),

    # wrap straddling midnight: 23:00-01:00
    ("23:00-01:00 @23:00 on",               slot(W(23,0,1,0), 0), 23, 0, True),
    ("23:00-01:00 @23:59 on",               slot(W(23,0,1,0), 0), 23, 59, True),
    ("23:00-01:00 @00:00 on",               slot(W(23,0,1,0), 0), 0, 0, True),
    ("23:00-01:00 @00:59 on",               slot(W(23,0,1,0), 0), 0, 59, True),
    ("23:00-01:00 @01:00 off (end excl.)",  slot(W(23,0,1,0), 0), 1, 0, False),
    ("23:00-01:00 @12:00 off",              slot(W(23,0,1,0), 0), 12, 0, False),

    # wider wrap 22:00-02:00 incl. exact midnight
    ("22:00-02:00 @23:00 on",               slot(W(22,0,2,0), 0), 23, 0, True),
    ("22:00-02:00 @00:00 on",               slot(W(22,0,2,0), 0), 0, 0, True),
    ("22:00-02:00 @01:00 on",               slot(W(22,0,2,0), 0), 1, 0, True),
    ("22:00-02:00 @02:00 off (end excl.)",  slot(W(22,0,2,0), 0), 2, 0, False),
    ("22:00-02:00 @12:00 off",              slot(W(22,0,2,0), 0), 12, 0, False),

    # minute-granularity edges on a wrap
    ("22:30-01:15 @22:29 off",              slot(W(22,30,1,15), 0), 22, 29, False),
    ("22:30-01:15 @22:30 on",               slot(W(22,30,1,15), 0), 22, 30, True),
    ("22:30-01:15 @01:14 on",               slot(W(22,30,1,15), 0), 1, 14, True),
    ("22:30-01:15 @01:15 off",              slot(W(22,30,1,15), 0), 1, 15, False),
]


def flat_regs(windows):
    """Flatten three {start,end} pairs to the 6-reg array acfirst expects."""
    out = []
    for s, e in windows:
        out.extend((s, e))
    return out


# --- backend: our firmware (ctypes into the real compiled acfirst.c) --------
class OursBackend:
    name = "ours (acfirst.c via ctypes)"

    def __init__(self, build_dir=None):
        import ctypes
        self.ctypes = ctypes
        build_dir = build_dir or os.path.join(ROOT, "build")
        os.makedirs(build_dir, exist_ok=True)
        so = os.path.join(build_dir, "libacfirst.so")
        src = os.path.join(ROOT, "src", "sched", "acfirst.c")
        # (re)build if missing or stale
        if (not os.path.exists(so)) or os.path.getmtime(so) < os.path.getmtime(src):
            cc = os.environ.get("HOSTCC", "cc")
            subprocess.run(
                [cc, "-std=c11", "-Wall", "-Wextra", "-fPIC", "-shared",
                 "-I" + os.path.join(ROOT, "include"), src, "-o", so],
                check=True)
        self.lib = ctypes.CDLL(so)
        self.fn = self.lib.acfirst_window_active
        self.fn.argtypes = [ctypes.POINTER(ctypes.c_uint16),
                            ctypes.c_int, ctypes.c_uint16]
        self.fn.restype = ctypes.c_bool

    def available(self):
        return True

    def active(self, windows, hour, minute):
        regs = flat_regs(windows)
        arr = (self.ctypes.c_uint16 * len(regs))(*regs)
        return bool(self.fn(arr, len(windows), self.ctypes.c_uint16(now_minutes(hour, minute))))


# --- backend: the factory evaluator, called in isolation under Unicorn ------
# Per-image addresses. "com_flat" matches the committed experiment
# tools/emu_acfirst.py on reference/com_flat.bin (the 244080-byte 05-series ARM
# image). "ceaa07" lists the 07-series addresses from docs/25 §3; mark it
# unverified-in-this-harness until a contributor confirms the isolated call on
# that image. Both evaluate the three windows at SETTINGS+win_off (4-byte stride,
# start@+0, end@+2) against the RTC, and set bit 24 of `status_word`.
PROFILES = {
    "com_flat": dict(
        eval_entry=0x0801ECE8,   # caller of sub_0801eb4c; mirrors bit24 after eval
        settings=0x20009854, win_off=0x64,
        rtc=0x2000A718,          # +1 = minute, +2 = hour
        win_timer=0x2000A98C,    # debounce; 0 => evaluate now
        status_word=0x2000A758,  # bit 24 = any AC-First window active
        verified=True,
    ),
    "ceaa07": dict(
        eval_entry=0x080352D0,   # sub_080352d0 (docs/25); reads RTC min/hour +
                                 # the 3 AC-First windows at settings+0x64..+0x6e
        settings=0x2000C85C, win_off=0x64,
        rtc=0x2000D850,          # +1 = minute, +2 = hour (calendar 0x2000d850)
        win_timer=None,
        status_word=0x2000D890,  # bit 24 = any AC-First window active
        verified=True,           # confirmed green on ceaa-07xx_vE_260214
    ),
}


def _seed_and_eval(Emu, p, image, symbols, windows, hour, minute):
    """Seed only the RTC + window config a window evaluator reads, call it in
    isolation, and return its 'any window active now' verdict (status bit 24)."""
    emu = Emu(image, symbols)                   # fresh sandbox per call
    regs = flat_regs(windows)
    emu.wbytes(p["settings"] + 0x60, bytes(0x30))          # clear the window region
    for i in range(len(windows)):
        base = p["settings"] + p["win_off"] + 4 * i        # start@+0, end@+2, stride 4
        emu.uc.mem_write(base + 0, struct.pack("<H", regs[2 * i] & 0xFFFF))
        emu.uc.mem_write(base + 2, struct.pack("<H", regs[2 * i + 1] & 0xFFFF))
    emu.uc.mem_write(p["settings"] + 0x0b, struct.pack("<H", 0x0100))  # enable config paths
    emu.uc.mem_write(p["settings"] + 0x1a, bytes([0x01]))
    emu.wbytes(p["rtc"], bytes(8))
    emu.uc.mem_write(p["rtc"] + 1, bytes([minute & 0xFF]))
    emu.uc.mem_write(p["rtc"] + 2, bytes([hour & 0xFF]))
    if p["win_timer"] is not None:
        emu.w32(p["win_timer"] & ~1, 0)                    # debounce off -> evaluate now
    emu.w32(p["status_word"], 0)
    emu.call(p["eval_entry"])
    return bool((emu.r32(p["status_word"]) >> 24) & 1)


class Skip(Exception):
    pass


class FactoryBackend:
    """The factory AC-First evaluator, called in isolation under Unicorn.

    profile="auto" (default) identifies the right PROFILES entry for the given
    image by probing: the entry whose evaluator reads active at 07:00 and
    inactive at 09:00 for a 06:00-08:00 window. So `make test-window` works for
    either the 05-series (com_flat) or 07-series (ceaa07) image with no flag.
    """
    def __init__(self, image, symbols=None, profile="auto"):
        self.image = image
        self.symbols = symbols
        self.requested = profile
        self._p = None if profile == "auto" else PROFILES[profile]
        self._pname = profile
        self.name = "factory (%s, %s)" % (os.path.basename(image or "?"), profile)
        self._Emu = None

    def available(self):
        if not self.image or not os.path.exists(self.image):
            return False
        try:
            import unicorn  # noqa: F401
        except Exception:
            return False
        return True

    def _emu(self):
        if self._Emu is None:
            import sys
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            from emu import Emu
            self._Emu = Emu
        return self._Emu

    def _resolve(self):
        if self._p is not None:
            return self._p
        Emu = self._emu()
        probe = slot(W(6, 0, 8, 0), 0)
        for name, p in PROFILES.items():
            try:
                # a wrong profile may fault; emu prints a stop line -- hush it
                with contextlib.redirect_stdout(io.StringIO()):
                    on = _seed_and_eval(Emu, p, self.image, self.symbols, probe, 7, 0)
                    off = _seed_and_eval(Emu, p, self.image, self.symbols, probe, 9, 0)
            except Exception:
                continue
            if on and not off:
                self._p, self._pname = p, name
                self.name = "factory (%s, %s)" % (os.path.basename(self.image), name)
                return p
        raise Skip("could not identify a factory evaluator profile for %s"
                   % os.path.basename(self.image or "?"))

    def active(self, windows, hour, minute):
        if not self.available():
            raise Skip("needs unicorn + factory image (%s)" % self.image)
        return _seed_and_eval(self._emu(), self._resolve(),
                              self.image, self.symbols, windows, hour, minute)
