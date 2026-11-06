"""Shared contract for the focused time-window micro-tests (docs/35).

The expensive full-simulator suite (tests/test_arm_sim.py) boots an entire
firmware image and talks Modbus to reach the AC-First status bit. That is
valuable but slow, and it gets slower as the harness grows. This module backs a
*narrow* alternative: exercise ONLY the "is the clock inside an AC-First window
now?" logic, two ways, against ONE set of vectors:

  * OursBackend    -- calls our firmware's acfirst_window_active() under Unicorn,
                      resolved by SYMBOL from build/firmware.elf and invoked with
                      the real ARM calling convention -- the SAME strategy as the
                      factory backend. Needs unicorn + a built firmware (`make`).
  * FactoryBackend -- calls just the factory ARM evaluator in Unicorn, with only
                      the RTC + window registers seeded (no boot). This is the
                      same isolated-call recipe as tools/emu_acfirst.py, reduced
                      to a function. Needs unicorn and a factory image.

Each backend skips cleanly when its prerequisites are absent. (Host-only,
toolchain-free coverage of the pure function lives in tests/test_acfirst.c.)

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


# --- backend: our firmware, run under Unicorn by SYMBOL ---------------------
# The SAME strategy as the factory backend: load the built ARM image and call one
# function in isolation. We call acfirst_window_active() through the real ARM
# calling convention (r0 = regs pointer, r1 = n windows, r2 = now_min) and read
# the boolean from r0 -- so our code is exercised exactly as the firmware runs it,
# not as host x86. The function is resolved by SYMBOL from the ELF (not a
# hard-coded address, which shifts between builds). Needs unicorn + a built
# firmware (build/firmware.bin + .elf; run `make`).
class OursBackend:
    def __init__(self, bin_path=None, elf_path=None):
        self.bin = bin_path or os.path.join(ROOT, "build", "firmware.bin")
        self.elf = elf_path or os.path.join(ROOT, "build", "firmware.elf")
        self.name = "ours (%s: acfirst_window_active by symbol)" % os.path.basename(self.bin)
        self._Emu = None
        self._addr = None

    def available(self):
        if not (os.path.exists(self.bin) and os.path.exists(self.elf)):
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

    def _sym(self, name):
        if self._addr is None:
            import shutil
            nm = shutil.which("arm-none-eabi-nm") or shutil.which("nm") or "nm"
            for line in subprocess.check_output([nm, self.elf], text=True).splitlines():
                p = line.split()
                if len(p) >= 3 and p[2] == name:
                    self._addr = int(p[0], 16)   # Emu.call sets the Thumb bit
                    break
            if self._addr is None:
                raise Skip("symbol %s not found in %s" % (name, self.elf))
        return self._addr

    def active(self, windows, hour, minute):
        if not self.available():
            raise Skip("needs unicorn + a built firmware (run `make`): %s" % self.bin)
        emu = self._emu()(self.bin, None)         # fresh sandbox per call
        regs = flat_regs(windows)
        scratch = 0x20008000                       # RAM scratch, below the stack
        emu.wbytes(scratch, b"".join(struct.pack("<H", r & 0xFFFF) for r in regs))
        r0 = emu.call(self._sym("acfirst_window_active"),
                      args=(scratch, len(windows), now_minutes(hour, minute)))
        return bool(r0 & 1)


# --- backends: the factory window evaluators, called in isolation under Unicorn -
# Each is a standalone factory function that reads the RTC + its window registers
# and sets an "active now" flag -- no boot. Addresses were recovered by finding
# the `now = 60*hour + minute` sites in the image and the window offset each loops
# over (see docs/35). Variants cover the 05-series (ceaa05) and 07-series
# (ceaa07) images; `profile="auto"` probes which one the given image matches.
EVALUATORS = {
    # AC-First load windows (HR 152-157), surfaced as IR 126 bit 8.
    "acfirst": [
        dict(variant="ceaa05",                        # 05-series (emu_acfirst.py)
             eval_entry=0x0801ECE8, settings=0x20009854, win_off=0x64,
             rtc=0x2000A718, win_timer=0x2000A98C, enable=None,
             result=("statusbit", 0x2000A758, 24)),
        dict(variant="ceaa07",                        # 07-series (docs/25) -- verified
             eval_entry=0x080352D0, settings=0x2000C85C, win_off=0x64,
             rtc=0x2000D850, win_timer=None, enable=None,
             result=("statusbit", 0x2000D890, 24)),
    ],
    # AC-charge windows (HR 68-73), gated by ACChargeType (stSysEnable, config
    # +0x33 bits 1-3); evaluator sub_08034590 writes a per-window mask at dbb7.
    # These share AC-First's window semantics (start-incl/end-excl/wrap), which
    # the shared VECTORS prove against our one generic acfirst_window_active().
    "acchg": [
        dict(variant="ceaa07",                        # 07-series -- verified
             eval_entry=0x08034590, settings=0x2000C85C, win_off=0x3a,
             rtc=0x2000D850, win_timer=None, enable=(0x33, 0x02),  # ACChargeType=1 (by time)
             result=("mask", 0x2000DBB7)),
    ],
}


def _seed_and_eval(Emu, spec, image, symbols, windows, hour, minute):
    """Seed only the RTC + window config (+ any feature-enable gate) the evaluator
    reads, call it in isolation, and return its 'any window active now' verdict."""
    emu = Emu(image, symbols)                   # fresh sandbox per call
    regs = flat_regs(windows)
    s = spec["settings"]
    emu.wbytes(s + 0x30, bytes(0x40))                      # clear a generous config span
    for i in range(len(windows)):
        base = s + spec["win_off"] + 4 * i                 # start@+0, end@+2, stride 4
        emu.uc.mem_write(base + 0, struct.pack("<H", regs[2 * i] & 0xFFFF))
        emu.uc.mem_write(base + 2, struct.pack("<H", regs[2 * i + 1] & 0xFFFF))
    emu.uc.mem_write(s + 0x0b, struct.pack("<H", 0x0100))  # AC-First enable paths (harmless)
    emu.uc.mem_write(s + 0x1a, bytes([0x01]))
    if spec.get("enable") is not None:                     # feature-enable gate (e.g. ACChargeType)
        off, val = spec["enable"]
        emu.uc.mem_write(s + off, bytes([val]))
    emu.wbytes(spec["rtc"], bytes(8))
    emu.uc.mem_write(spec["rtc"] + 1, bytes([minute & 0xFF]))
    emu.uc.mem_write(spec["rtc"] + 2, bytes([hour & 0xFF]))
    if spec.get("win_timer") is not None:
        emu.w32(spec["win_timer"] & ~1, 0)                 # debounce off -> evaluate now
    kind = spec["result"][0]
    if kind == "statusbit":
        _, addr, bit = spec["result"]
        emu.w32(addr, 0)
        emu.call(spec["eval_entry"])
        return bool((emu.r32(addr) >> bit) & 1)
    _, addr = spec["result"]                               # "mask": nonzero per-window byte
    emu.uc.mem_write(addr, b"\x00")
    emu.call(spec["eval_entry"])
    return emu.rbytes(addr, 1)[0] != 0


class Skip(Exception):
    pass


class FactoryBackend:
    """A factory window evaluator (window_type), called in isolation under Unicorn.

    window_type selects which evaluator ("acfirst" or "acchg"); profile="auto"
    (default) identifies the right image variant for that type by probing: the
    variant whose evaluator reads active at 07:00 and inactive at 09:00 for a
    06:00-08:00 window. So `make test-window` works for either the 05-series
    (ceaa05) or 07-series (ceaa07) image with no flag.
    """
    def __init__(self, image, symbols=None, window_type="acfirst", profile="auto"):
        self.image = image
        self.symbols = symbols
        self.window_type = window_type
        self.requested = profile
        self._spec = None
        self._Emu = None
        self.name = "factory (%s, %s/%s)" % (
            os.path.basename(image or "?"), window_type, profile)
        if profile != "auto":
            for sp in EVALUATORS[window_type]:
                if sp["variant"] == profile:
                    self._spec = sp
            if self._spec is None:
                raise Skip("no %s evaluator variant %r" % (window_type, profile))

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
        if self._spec is not None:
            return self._spec
        Emu = self._emu()
        probe = slot(W(6, 0, 8, 0), 0)
        for sp in EVALUATORS[self.window_type]:
            try:
                # a wrong variant may fault; emu prints a stop line -- hush it
                with contextlib.redirect_stdout(io.StringIO()):
                    on = _seed_and_eval(Emu, sp, self.image, self.symbols, probe, 7, 0)
                    off = _seed_and_eval(Emu, sp, self.image, self.symbols, probe, 9, 0)
            except Exception:
                continue
            if on and not off:
                self._spec = sp
                self.name = "factory (%s, %s/%s)" % (
                    os.path.basename(self.image), self.window_type, sp["variant"])
                return sp
        raise Skip("could not identify a factory %s evaluator for %s"
                   % (self.window_type, os.path.basename(self.image or "?")))

    def active(self, windows, hour, minute):
        if not self.available():
            raise Skip("needs unicorn + factory image (%s)" % self.image)
        return _seed_and_eval(self._emu(), self._resolve(),
                              self.image, self.symbols, windows, hour, minute)
