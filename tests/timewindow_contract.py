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


# --- the shared vectors -----------------------------------------------------
# Each: (name, windows, hour, minute, expected_active). `windows` is always three
# {start,end} pairs (6 packed regs) to match HR 152-157 / ACFIRST_NUM_WINDOWS.
# Mirrors tests/test_acfirst.c so all three layers (host C, ctypes, factory)
# are held to one spec: start-inclusive, end-exclusive, midnight wrap, empty
# window never active, multi-window OR.
_EMPTY = (0, 0)
_W_6_8 = W(6, 0, 8, 0)      # 06:00-08:00
_WRAP = W(22, 0, 2, 0)      # 22:00-02:00 (wraps midnight)

VECTORS = [
    # single window 06:00-08:00
    ("05:59 off (before start)",     (_W_6_8, _EMPTY, _EMPTY), 5, 59, False),
    ("06:00 active (start incl.)",   (_W_6_8, _EMPTY, _EMPTY), 6,  0, True),
    ("07:30 active",                 (_W_6_8, _EMPTY, _EMPTY), 7, 30, True),
    ("07:59 active",                 (_W_6_8, _EMPTY, _EMPTY), 7, 59, True),
    ("08:00 off (end excl.)",        (_W_6_8, _EMPTY, _EMPTY), 8,  0, False),
    ("09:00 off (after end)",        (_W_6_8, _EMPTY, _EMPTY), 9,  0, False),
    # empty window (start == end) never active
    ("empty window never active",    (W(3, 0, 3, 0), _EMPTY, _EMPTY), 3, 0, False),
    # midnight wrap 22:00-02:00
    ("23:00 in wrap window",         (_WRAP, _EMPTY, _EMPTY), 23, 0, True),
    ("01:00 in wrap window",         (_WRAP, _EMPTY, _EMPTY), 1,  0, True),
    ("02:00 off (wrap end excl.)",   (_WRAP, _EMPTY, _EMPTY), 2,  0, False),
    ("12:00 off (outside wrap)",     (_WRAP, _EMPTY, _EMPTY), 12, 0, False),
    # multi-window OR: window 0 empty, window 1 matches
    ("07:00 active via window 1",    (_EMPTY, _W_6_8, _EMPTY), 7, 0, True),
    # all windows empty -> never active
    ("all-empty off",               (_EMPTY, _EMPTY, _EMPTY), 10, 0, False),
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
        eval_entry=0x080352D0,   # sub_080352d0 (docs/25)
        settings=0x2000C85C, win_off=0x64,
        rtc=0x2000D850,          # +1 = minute, +2 = hour (calendar 0x2000d850)
        win_timer=None,
        status_word=0x2000D890,  # bit 24 = any AC-First window active
        verified=False,
    ),
}


class Skip(Exception):
    pass


class FactoryBackend:
    def __init__(self, image, symbols=None, profile="com_flat"):
        self.image = image
        self.symbols = symbols
        self.profile_name = profile
        self.p = PROFILES[profile]
        self.name = "factory (%s, %s)" % (os.path.basename(image), profile)
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

    def active(self, windows, hour, minute):
        if not self.available():
            raise Skip("needs unicorn + factory image (%s)" % self.image)
        Emu = self._emu()
        p = self.p
        emu = Emu(self.image, self.symbols)   # fresh sandbox per vector (no state bleed)
        regs = flat_regs(windows)
        # seed only the window config + RTC the evaluator reads
        emu.wbytes(p["settings"] + 0x60, bytes(0x20))          # clear window region
        for i in range(len(windows)):
            base = p["settings"] + p["win_off"] + 4 * i
            emu.uc.mem_write(base + 0, struct.pack("<H", regs[2 * i] & 0xFFFF))
            emu.uc.mem_write(base + 2, struct.pack("<H", regs[2 * i + 1] & 0xFFFF))
        emu.uc.mem_write(p["settings"] + 0x0b, struct.pack("<H", 0x0100))  # enable config paths
        emu.uc.mem_write(p["settings"] + 0x1a, bytes([0x01]))
        emu.wbytes(p["rtc"], bytes(8))
        emu.uc.mem_write(p["rtc"] + 1, bytes([minute & 0xFF]))
        emu.uc.mem_write(p["rtc"] + 2, bytes([hour & 0xFF]))
        if p["win_timer"] is not None:
            emu.w32(p["win_timer"] & ~1, 0)
        emu.w32(p["status_word"], 0)
        emu.call(p["eval_entry"])
        return bool((emu.r32(p["status_word"]) >> 24) & 1)
