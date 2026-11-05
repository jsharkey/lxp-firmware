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
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, load_symbols_nm, load_symbols_csv
from tft import attach_tft, mono, W, H, PANEL_W, PANEL_H
from unicorn import UC_HOOK_MEM_READ

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

    def boot(self, warmup=2_000_000):
        """Boot through config + scheduler until the display task has painted a
        stable screen. Returns self."""
        t0 = time.time()
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
