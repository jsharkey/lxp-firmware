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


class FactoryHmi:
    def __init__(self, image="reference/com_flat.bin", symbols="reference/symbols.csv",
                 verbose=True):
        self.verbose = verbose
        self.sim = ArmSim.from_image(image, symbols=symbols)
        self.sim.attach_config_flash(cs_pin="PA4", spi_base=0x40013000)
        self.sim.uc.hook_add(UC_HOOK_MEM_READ, self._can_ready, begin=CAN_BASE, end=CAN_END)
        self.tft = attach_tft(self.sim)
        for k in KEYS:
            self.sim.set_input(k, 1)       # keys released (pull-ups) before boot
        self.sim.enable_rtos(interval=20000)
        self.sim.enable_systick(interval=20000)
        self._booted = False

    @staticmethod
    def _can_ready(uc, access, addr, size, value, ud):
        uc.mem_write(addr & ~3, (0xFFFFFFFF).to_bytes(4, "little")); return True

    def _log(self, *a):
        if self.verbose: print(*a, flush=True)

    def _run(self, n):
        try: self.sim.run(n)
        except Exception: pass

    def boot(self, warmup=42_000_000):
        """Boot through config + scheduler until the display task has painted a
        stable screen. Returns the number of lit pixels."""
        t0 = time.time()
        self._log("factory HMI: booting through RTOS (~90s) ...")
        try: self.sim.run_reset(max_insn=warmup)
        except Exception: pass
        self._settle(max_chunks=10)
        self._booted = True
        self._log("  booted, screen settled (%d px, %.0fs)"
                  % (int((self.tft.gram != 0).sum()), time.time() - t0))
        return self

    def _settle(self, chunk=4_000_000, max_chunks=8, stable=2):
        """Run until the GRAM stops changing (a full redraw has landed), or the
        chunk budget is spent. Returns when `stable` consecutive chunks match."""
        prev = self.tft.gram.copy()
        same = 0
        for _ in range(max_chunks):
            self._run(chunk)
            cur = self.tft.gram
            if np.array_equal(cur, prev) and int((cur != 0).sum()) > 200:
                same += 1
                if same >= stable:
                    break
            else:
                same = 0
            prev = cur.copy()

    def press(self, key, hold=5_000_000):
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
