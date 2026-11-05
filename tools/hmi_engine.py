#!/usr/bin/env python3
"""
hmi_engine — run the open firmware's HMI in the emulator and expose it as a
simple screen+keys object for an app or a test.

It loads our build (build/firmware.{bin,elf}) into tools/arm_sim.py, attaches the
I2C character-LCD model (tools/panel.py), seeds a plausible telemetry snapshot,
then drives the *real* firmware functions:

    hmi_lcd_init / hmi_keypad_init / hmi_init  (bring-up)
    press(key): inject the key GPIO (active-low), poll the firmware's debounced
                keypad reader until it latches the key, dispatch hmi_key, then
                hmi_render -> the firmware bit-bangs the new screen over I2C,
                which the panel model decodes into .screen()

So the text you read back is produced by compiled firmware rendering to a
modelled LCD over a modelled I2C bus — not a Python reimplementation.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, load_symbols_nm
import panel

# Register indices (include/inv/modbus_map.h) for the seed snapshot.
IR = {"STATE": 0, "VBAT": 4, "SOC_SOH": 5, "FAC": 15}
HR = {"CHARGE_VOLT_REF": 99, "CHARGE_CURR": 101, "DISCHG_CURR": 102, "EOD": 105,
      "EPS_VOLT_SET": 90, "EPS_FREQ_SET": 91, "OUTPUT_PRIO_CFG": 145,
      "LINE_MODE": 146, "SET_SYSTEM_TYPE": 112, "GEN_CHG_START_V": 194}

# A believable running snapshot so INFO rows show live-looking values.
SEED_IR = {"STATE": 3, "VBAT": 525, "SOC_SOH": 85, "FAC": 6000}
SEED_HR = {"EPS_VOLT_SET": 1, "EPS_FREQ_SET": 1, "OUTPUT_PRIO_CFG": 0,
           "LINE_MODE": 0, "CHARGE_CURR": 80, "DISCHG_CURR": 100,
           "CHARGE_VOLT_REF": 560, "EOD": 20, "SET_SYSTEM_TYPE": 0,
           "GEN_CHG_START_V": 480}

KEY_ENUM = {"up": 0, "down": 1, "enter": 2, "esc": 3}  # hmi_key_t order


class HmiSim:
    def __init__(self, bin_path="build/firmware.bin", elf_path="build/firmware.elf"):
        self.sim = ArmSim(bin_path, load_symbols_nm(elf_path))
        self.lcd = panel.attach_panel(self.sim)
        self._boot()

    # ---- bring-up -------------------------------------------------------
    def _seed(self):
        s = self.sim
        g_rt = s.sym("g_rt")
        ir_base = g_rt                     # uint16 input_reg[160]
        hr_base = g_rt + 2 * 160           # uint16 holding_reg[256]
        for name, val in SEED_IR.items():
            s.wbytes(ir_base + 2 * IR[name], bytes([val & 0xFF, (val >> 8) & 0xFF]))
        for name, val in SEED_HR.items():
            s.wbytes(hr_base + 2 * HR[name], bytes([val & 0xFF, (val >> 8) & 0xFF]))

    def _boot(self):
        s = self.sim
        panel.keys_idle(s)                 # all keys released (IDR high) before init
        s.call("hmi_lcd_init")
        s.call("hmi_keypad_init")
        panel.keys_idle(s)                 # keypad_init drove the pull-ups; re-assert
        self._seed()
        s.call("hmi_init", (s.sym("g_hmi"), s.sym("hmi_root_menu"), s.sym("g_hmi_io")))
        self._render()

    # ---- drive ----------------------------------------------------------
    def _render(self):
        self.sim.call("hmi_render", (self.sim.sym("g_hmi"),))

    def _poll(self):
        r = self.sim.call("hmi_keypad_poll") & 0xFFFFFFFF
        return -1 if r == 0xFFFFFFFF else r

    def press(self, key):
        """Press one key through the real GPIO + debounce path, then render."""
        if key not in KEY_ENUM:
            raise ValueError("unknown key %r" % key)
        s = self.sim
        panel.key_press(s, key)
        got = -1
        for _ in range(10):                # let the debounce latch the press
            got = self._poll()
            if got >= 0:
                break
        panel.key_release(s, key)
        for _ in range(6):                 # settle the release so it re-arms
            self._poll()
        if got < 0:
            got = KEY_ENUM[key]            # fallback: dispatch the intended key
        s.call("hmi_key", (s.sym("g_hmi"), got))
        self._render()
        return got

    # ---- read-out -------------------------------------------------------
    def screen(self):
        """The 4 LCD rows exactly as the firmware drew them (list of str)."""
        return self.lcd.text()

    def selected(self):
        """The currently highlighted row's text (the one with the '>' cursor),
        or '' if none is highlighted."""
        for row in self.screen():
            if row.startswith(">"):
                return row[1:]
        return ""

    def holding(self, name):
        """Read a holding register (by HR name) out of the firmware's store."""
        g_rt = self.sim.sym("g_rt")
        off = g_rt + 2 * 160 + 2 * HR[name]
        b = self.sim.rbytes(off, 2)
        return b[0] | (b[1] << 8)

    def nav_to(self, needle, key="down", limit=40):
        """Press `key` until the highlighted row contains `needle`. Returns True
        if found. Robust to menu reordering (navigates by label, not index)."""
        for _ in range(limit):
            if needle in self.selected():
                return True
            self.press(key)
        return needle in self.selected()

    def set_input_reg(self, name, val):
        """Update a live telemetry input register (e.g. to animate the display)."""
        g_rt = self.sim.sym("g_rt")
        self.sim.wbytes(g_rt + 2 * IR[name], bytes([val & 0xFF, (val >> 8) & 0xFF]))
        self._render()


if __name__ == "__main__":
    h = HmiSim(*(sys.argv[1:3] or []))
    def show(tag):
        print("--- %s" % tag)
        for row in h.screen():
            print("|%-20s|" % row)
    show("boot")
    for k in ["down", "down", "enter", "up", "esc", "down", "down", "down", "enter"]:
        h.press(k)
        show("press %s" % k)
