#!/usr/bin/env python3
"""
factory_hmi — run the *factory* ARM HMI in the emulator and drive it like the
real device: boot it through its RTOS to a live screen, read what it draws to
its 128x160 TFT (tools/tft.py), and press the four front-panel keys so the real
firmware navigates its own menus.

    key GPIO (PA8/PA11/PC8/PC9)  ->  factory key task  ->  menu/screen handlers
        ->  bit-banged 4-wire TFT writes  ->  tools/tft.py GRAM  ->  mono image

Everything on screen is the factory image's own draw code executing under the
Unicorn harness (tools/arm_sim.py) with the full RTOS engine (docs/19): config
flash provisioned, exception/PendSV scheduler on, SysTick injected. No Python
reimplements the HMI.

Boot takes ~90s (tens of millions of instructions through config + scheduler
until the display task paints); each keypress then runs the firmware until the
screen settles. Needs `pip install unicorn` and reference/com_flat.bin +
reference/symbols.csv.
"""
import os, sys, time, gzip, pickle, hashlib
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, load_symbols_nm, load_symbols_csv
from tft import attach_tft, mono, W, H, PANEL_W, PANEL_H
from unicorn import UC_HOOK_MEM_READ
import unicorn.arm_const as _ac

# CPU registers to persist in the boot cache, by name -> Unicorn constant, in the
# order they are restored (modes/masks first, stacks next, GP + PC last). We save
# the registers explicitly rather than Unicorn's opaque context blob: pickling a
# UcContext and restoring it into a fresh emulator corrupts the heap (that was the
# segfault in the first cache attempt); plain register ints round-trip cleanly.
_CACHE_REGS = {}
for _n in ("CPSR", "CONTROL", "PRIMASK", "BASEPRI", "FAULTMASK", "MSP", "PSP", "SP",
           "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7",
           "R8", "R9", "R10", "R11", "R12", "LR", "PC"):
    _c = getattr(_ac, "UC_ARM_REG_" + _n, None)
    if _c is not None:
        _CACHE_REGS[_n] = _c

# Front-panel keys (docs/16): PA8, PA11, PC8, PC9, active-low. Functional names
# recovered by driving the factory menu (docs/23): PA11 is ENTER/select.
KEYS = ["PA8", "PA11", "PC8", "PC9"]

CAN_BASE = 0x40006400          # bxCAN; fake its "ready" bits so the CAN-poll task
CAN_END  = 0x40006420          # doesn't burn its slice spinning (docs/19)

# SysTick cadence: how many emulated instructions between injected 1 ms ticks.
# The firmware's splash/init/redraw waits are measured in ticks, so a smaller
# interval = a faster emulated clock = those waits finish in far fewer
# instructions. 4000 is the sweet spot measured on this image (boot ~3x faster
# than the harness default of 20000, identical screen); going much lower makes
# the SysTick ISR preempt the display task so often it never finishes a repaint.
TICK = 4000


def _resolve_symbols(firmware, symbols):
    """Best-effort symbol table (the renderer never needs it, but it's handy):
    an explicit .elf/.csv, else the .elf beside a build/*.bin, else the factory
    reference/symbols.csv, else none."""
    try:
        if symbols and symbols.endswith(".elf"): return load_symbols_nm(symbols)
        if symbols and symbols.endswith(".csv"): return load_symbols_csv(symbols)
        if firmware.endswith(".bin"):
            elf = firmware[:-4] + ".elf"
            if os.path.exists(elf): return load_symbols_nm(elf)
        if os.path.exists("reference/symbols.csv"): return load_symbols_csv("reference/symbols.csv")
    except Exception:
        pass
    return {}


class FactoryHmi:
    """Runs ANY firmware image for this MCU and renders its LCD output. Pass a
    firmware path (a vendor .hex or a flat .bin); with none, it uses the
    open-source build (build/firmware.bin). The harness is identical either way
    (config flash, RTOS engine, SysTick, the LCD + key model), so the simulator
    is agnostic about which firmware it runs."""
    def __init__(self, firmware=None, symbols=None, verbose=True, tick=TICK):
        self.verbose = verbose
        self.firmware = firmware or "build/firmware.bin"
        self.sim = ArmSim.from_image(self.firmware, symbols=_resolve_symbols(self.firmware, symbols))
        self.sim.attach_config_flash(cs_pin="PA4", spi_base=0x40013000)
        self.sim.uc.hook_add(UC_HOOK_MEM_READ, self._can_ready, begin=CAN_BASE, end=CAN_END)
        self.tft = attach_tft(self.sim)
        for k in KEYS:
            self.sim.set_input(k, 1)       # keys released (pull-ups) before boot
        self.sim.enable_rtos(interval=tick)
        self.sim.enable_systick(interval=tick)
        self._booted = False

    @staticmethod
    def _can_ready(uc, access, addr, size, value, ud):
        uc.mem_write(addr & ~3, (0xFFFFFFFF).to_bytes(4, "little")); return True

    def _log(self, *a):
        if self.verbose: print(*a, flush=True)

    def _run(self, n):
        try: self.sim.run(n)
        except Exception: pass

    # ---- boot cache -----------------------------------------------------
    # Booting runs tens of millions of instructions (the faithful RTOS). It is
    # deterministic, so we cache the exact post-boot machine to disk and restore
    # it in ~1 s on later launches. The cache is keyed by the firmware's content
    # hash (a rebuilt image re-boots) + the tick + CACHE_VER. It lives in a
    # gitignored directory and is DERIVED from the firmware image — so a factory
    # cache is proprietary and must never be committed; each user generates their
    # own once.
    CACHE_VER = 1
    CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".hmi_cache")
    _RTOS_ATTRS = ("_exc_depth", "_thread_on_psp", "_msp", "_systick_due", "_pendsv_req")

    def _cache_path(self):
        try:
            h = hashlib.md5(open(self.firmware, "rb").read()).hexdigest()[:12]
        except Exception:
            return None
        return os.path.join(self.CACHE_DIR, "boot_%s_t%d_v%d.pkl.gz" % (h, TICK, self.CACHE_VER))

    def _save_cache(self, path):
        uc = self.sim.uc
        blob = {
            "v": self.CACHE_VER,
            "regs": {n: uc.reg_read(c) for n, c in _CACHE_REGS.items()},
            "mem": [(b, e - b + 1, bytes(uc.mem_read(b, e - b + 1)))
                    for (b, e, _p) in uc.mem_regions()],
            "shadow": dict(self.sim.shadow),
            "rtos": {**{a: getattr(self.sim, a) for a in self._RTOS_ATTRS},
                     "_pending_irqs": list(self.sim._pending_irqs)},
            "gram": self.tft.gram.tobytes(), "shape": self.tft.gram.shape,
        }
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp%d" % os.getpid()
        with gzip.open(tmp, "wb", compresslevel=4) as f:
            pickle.dump(blob, f, protocol=4)
        os.replace(tmp, path)                    # atomic publish

    def _load_cache(self, path):
        with gzip.open(path, "rb") as f:
            blob = pickle.load(f)
        if blob.get("v") != self.CACHE_VER:
            raise ValueError("stale cache version")
        uc = self.sim.uc
        have = [(b, e) for (b, e, _p) in uc.mem_regions()]
        for (b, s, data) in blob["mem"]:
            if not any(hb <= b and b + s - 1 <= he for (hb, he) in have):
                uc.mem_map(b, s)                 # an auto-mapped page a fresh machine lacks
                have.append((b, b + s - 1))
            uc.mem_write(b, data)
        for n, c in _CACHE_REGS.items():
            uc.reg_write(c, blob["regs"][n])
        self.sim.shadow = dict(blob["shadow"])
        for a in self._RTOS_ATTRS:
            setattr(self.sim, a, blob["rtos"][a])
        self.sim._pending_irqs = list(blob["rtos"]["_pending_irqs"])
        self.tft.gram = np.frombuffer(blob["gram"], dtype=np.uint8).reshape(blob["shape"]).copy()

    def boot(self, warmup=2_000_000, cache=True):
        """Boot until the display paints a stable screen — or restore the cached
        post-boot machine (instant). Returns self."""
        t0 = time.time()
        cp = self._cache_path() if cache else None
        if cp and os.path.exists(cp):
            try:
                self._load_cache(cp)
                self._booted = True
                self._log("restored %s from cache (%d px, %.1fs)"
                          % (os.path.basename(self.firmware),
                             int((self.tft.gram != 0).sum()), time.time() - t0))
                return self
            except Exception as e:
                self._log("cache restore failed (%s); booting fresh" % e)
        self._log("booting %s ..." % os.path.basename(self.firmware))
        try: self.sim.run_reset(max_insn=warmup)
        except Exception: pass
        # Settle on any stable non-blank screen. The floor must be low — the
        # factory overview is ~1500 lit px but the open build's "hello world" is
        # only tens — and the picture stabilises only after a full draw (mid-draw
        # chunks keep changing), so a low floor doesn't stop us early.
        self._settle(chunk=2_000_000, max_chunks=24, quiet=2, need=10)
        self._booted = True
        self._log("  booted, screen settled (%d px, %.0fs)"
                  % (int((self.tft.gram != 0).sum()), time.time() - t0))
        if cp:
            try: self._save_cache(cp)
            except Exception as e: self._log("cache save failed (%s)" % e)
        return self

    def _settle(self, chunk=800_000, max_chunks=30, quiet=2, jitter=90, need=200):
        """Run until the screen goes quiet — a repaint has landed and successive
        chunks differ by at most `jitter` pixels — then stop. `jitter` must be
        large enough to ignore the ticking on-screen clock (at the fast emulated
        clock the seconds roll several times during a boot, and a digit change is
        tens of pixels) but far below a real repaint (hundreds+). Stopping
        *promptly* also matters: a long settle burns enough device-time to trip
        the firmware's menu idle timeout and bounce back to the overview."""
        prev = self.tft.gram.copy()
        still = 0
        for _ in range(max_chunks):
            self._run(chunk)
            cur = self.tft.gram
            diff = int((cur != prev).sum())
            if diff <= jitter and int((cur != 0).sum()) >= need:
                still += 1
                if still >= quiet:
                    break
            else:
                still = 0
            prev = cur.copy()

    def press(self, key, hold=2_000_000):
        """Press one key (active-low) and run until the screen settles. `hold` is
        how long the key is held down (in instructions): it must span enough of
        the firmware's debounced key samples to latch — measured minimum ~1M, so
        1.2M gives margin while being ~3x shorter than a naive hold."""
        if key not in KEYS:
            raise ValueError("unknown key %r (use %s)" % (key, KEYS))
        self.sim.set_input(key, 0)
        self._run(hold)                 # hold low long enough for the debounced read
        self.sim.set_input(key, 1)
        self._settle()                  # let the handler redraw
        return self.screen()

    def gram(self):
        return self.tft.gram.copy()

    def screen(self, invert=True):
        """Current screen as the 240x160 monochrome panel image (dark ink on a
        light panel by default, as the device reads)."""
        return mono(self.tft.gram, invert=invert)

    def save_png(self, path, scale=3, invert=True):
        from PIL import Image
        img = self.screen(invert=invert)
        Image.fromarray(img).resize((PANEL_W * scale, PANEL_H * scale), 0).save(path)
        return path


if __name__ == "__main__":
    # usage: factory_hmi.py [firmware.hex|firmware.bin] [out.png]
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    fw = next((a for a in args if a.endswith((".hex", ".bin"))), None)
    out = next((a for a in args if a.endswith(".png")), "/tmp/hmi.png")
    h = FactoryHmi(firmware=fw).boot()
    h.save_png(out)
    print("saved", out)
