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
from arm_sim import ArmSim
from tft import attach_tft, mono, W, H
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


class FactoryHmi:
    def __init__(self, image="reference/com_flat.bin", symbols="reference/symbols.csv",
                 verbose=True, tick=TICK):
        self.verbose = verbose
        self.sim = ArmSim.from_image(image, symbols=symbols)
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
        self._log("factory HMI: booting through RTOS ...")
        try: self.sim.run_reset(max_insn=warmup)
        except Exception: pass
        self._settle(chunk=2_000_000, max_chunks=20, quiet=2, need=800)
        self._booted = True
        self._log("  booted, screen settled (%d px, %.0fs)"
                  % (int((self.tft.gram != 0).sum()), time.time() - t0))
        return self

    def _settle(self, chunk=800_000, max_chunks=30, quiet=2, jitter=30, need=200):
        """Run until the screen goes quiet — a repaint has landed and successive
        chunks differ by at most `jitter` pixels (the on-screen clock changes a
        few pixels each second, which must not count as "still drawing") — then
        stop. Stopping *promptly* matters: the emulated clock is fast, so a long
        settle would burn enough device-time to trip the firmware's menu idle
        timeout and bounce back to the overview before we capture the new screen."""
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

    def press(self, key, hold=3_000_000):
        """Press one key (active-low) and run until the screen settles."""
        if key not in KEYS:
            raise ValueError("unknown key %r (use %s)" % (key, KEYS))
        self.sim.set_input(key, 0)
        self._run(hold)                 # hold low long enough for the debounced read
        self.sim.set_input(key, 1)
        self._settle()                  # let the handler redraw
        return self.screen()

    def gram(self):
        return self.tft.gram.copy()

    def screen(self, invert=False):
        """Current screen as a monochrome HxW uint8 image (0/255)."""
        return mono(self.tft.gram, invert=invert)

    def save_png(self, path, scale=4, invert=False):
        from PIL import Image
        img = self.screen(invert=invert)
        Image.fromarray(img).resize((W * scale, H * scale), 0).save(path)
        return path


if __name__ == "__main__":
    h = FactoryHmi().boot()
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/factory_overview.png"
    h.save_png(out)
    print("saved", out)
