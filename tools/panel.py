#!/usr/bin/env python3
"""
panel — an emulator model of the HMI's 20x4 HD44780 character LCD (behind a
PCF8574 I2C backpack) and its four front-panel keys, for tools/arm_sim.py.

The firmware (src/hmi/hmi_port.c, wiring in include/inv/hmi_panel.h) bit-bangs
I2C on PE0/PE1 to a PCF8574 whose P0..P7 map to the HD44780's RS/RW/E/backlight
and high data nibble. This module decodes that exact contract back into a text
framebuffer, so the simulator can *see* what the running firmware draws:

    I2C bits  ->  PCF8574 port bytes  ->  HD44780 nibbles  ->  DDRAM  ->  text

`attach_panel(sim)` hooks GPIOE writes on an ArmSim and returns an I2cLcd whose
.text() is the 4 rendered rows. Keys are injected with press()/release()/tap()
on the real key GPIOs (PA8/PA11/PC8/PC9, active-low).

Pure model; decodes by bit/nibble order, not timing. No hardware.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import GPIO, R_BSRR, R_BRR, R_ODR, parse_pin
from unicorn import UC_HOOK_MEM_WRITE

# --- panel wiring: mirror of include/inv/hmi_panel.h (single source of truth) --
SCL_PIN = "PE0"
SDA_PIN = "PE1"
PCF8574_ADDR = 0x27
BP_RS, BP_RW, BP_EN, BP_BL = 0x01, 0x02, 0x04, 0x08
LCD_COLS, LCD_ROWS = 20, 4
# HD44780 DDRAM base address of each visible row (20x4 map)
ROW_BASE = {0x00: 0, 0x40: 1, 0x14: 2, 0x54: 3}
# key name -> GPIO pin (active low); UP/DOWN/ENTER/ESC per hmi_panel.h
KEYS = {"up": "PA8", "down": "PA11", "enter": "PC8", "esc": "PC9"}


class Hd44780:
    """HD44780 controller model: consumes 8-bit values tagged command/data and
    maintains a COLS x ROWS character matrix via DDRAM addressing."""
    def __init__(self, cols=LCD_COLS, rows=LCD_ROWS):
        self.cols, self.rows = cols, rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.addr = 0

    def _rowcol(self, addr):
        for base, row in ROW_BASE.items():
            if base <= addr < base + self.cols:
                return row, addr - base
        return None

    def command(self, b):
        if b & 0x80:                      # set DDRAM address
            self.addr = b & 0x7F
        elif b == 0x01:                   # clear display
            self.grid = [[" "] * self.cols for _ in range(self.rows)]
            self.addr = 0
        elif b in (0x02, 0x03):           # return home
            self.addr = 0
        # function set / entry mode / display on-off: no visible-state change here

    def data(self, b):
        rc = self._rowcol(self.addr)
        if rc is not None:
            r, c = rc
            self.grid[r][c] = chr(b) if 0x20 <= b < 0x7F else " "
        self.addr = (self.addr + 1) & 0x7F

    def text(self):
        return ["".join(row).rstrip() for row in self.grid]


class Pcf8574:
    """PCF8574 backpack: each written port byte latches an HD44780 nibble on the
    E falling edge; two nibbles (high then low) make a byte, tagged by RS."""
    def __init__(self, lcd):
        self.lcd = lcd
        self.prev_en = 0
        self.phase = 0          # 0 = expect high nibble, 1 = expect low
        self.high = 0

    def port_write(self, val):
        en = val & BP_EN
        if self.prev_en and not en:          # E falling edge -> latch nibble
            nib = (val >> 4) & 0x0F
            rs = val & BP_RS
            if self.phase == 0:
                self.high = nib
                self.phase = 1
            else:
                byte = (self.high << 4) | nib
                self.phase = 0
                if rs:
                    self.lcd.data(byte)
                else:
                    self.lcd.command(byte)
        self.prev_en = en


class I2cLcd:
    """Bit-banged-I2C sink: reconstructs SCL/SDA edges into I2C frames, pulls the
    PCF8574 port bytes out of each write transaction, and feeds the HD44780."""
    def __init__(self):
        self.lcd = Hd44780()
        self.pcf = Pcf8574(self.lcd)
        self.scl = 1
        self.sda = 1
        self.active = False     # inside START..STOP
        self.bits = 0           # bits seen in the current byte (0..8, 8=ACK)
        self.cur = 0
        self.is_addr = False    # next completed byte is the address
        self.addr_ok = False

    # -- I2C line-level decode --
    def _scl_edge(self, rising):
        if rising and self.active and self.bits < 8:
            self.cur = ((self.cur << 1) | self.sda) & 0xFF
            self.bits += 1
        elif rising and self.active and self.bits == 8:
            # 9th clock = ACK; byte complete
            if self.is_addr:
                self.addr_ok = (self.cur >> 1) == PCF8574_ADDR
                self.is_addr = False
            elif self.addr_ok:
                self.pcf.port_write(self.cur)
            self.cur = 0
            self.bits = 0

    def _start(self):
        self.active = True
        self.bits = 0
        self.cur = 0
        self.is_addr = True
        self.addr_ok = False

    def _stop(self):
        self.active = False
        self.bits = 0

    def on_line(self, new_scl, new_sda):
        # exactly one of SCL/SDA changes per firmware write
        if new_scl != self.scl:
            rising = (new_scl == 1)
            self.scl = new_scl
            self._scl_edge(rising)
        elif new_sda != self.sda:
            old = self.sda
            self.sda = new_sda
            if self.scl == 1:
                if old == 1 and new_sda == 0:
                    self._start()
                elif old == 0 and new_sda == 1:
                    self._stop()

    def text(self):
        return self.lcd.text()


def attach_panel(sim, scl_pin=SCL_PIN, sda_pin=SDA_PIN):
    """Attach an I2cLcd to an ArmSim: hook writes to the SCL/SDA port and drive
    the decoder from BSRR/BRR/ODR changes. Returns the I2cLcd."""
    dev = I2cLcd()
    sp, sb = parse_pin(scl_pin)
    dp, db = parse_pin(sda_pin)
    assert sp == dp, "SCL and SDA must share a GPIO port for this hook"
    base = GPIO[sp]
    # current driven levels (idle high)
    lvl = {"scl": 1, "sda": 1}

    def apply(set_mask, reset_mask):
        new_scl, new_sda = lvl["scl"], lvl["sda"]
        if (set_mask >> sb) & 1:   new_scl = 1
        if (reset_mask >> sb) & 1: new_scl = 0
        if (set_mask >> db) & 1:   new_sda = 1
        if (reset_mask >> db) & 1: new_sda = 0
        # feed SCL change first, then SDA (firmware changes one per write anyway)
        if new_scl != lvl["scl"]:
            lvl["scl"] = new_scl
            dev.on_line(new_scl, lvl["sda"])
        if new_sda != lvl["sda"]:
            lvl["sda"] = new_sda
            dev.on_line(lvl["scl"], new_sda)

    def hook(uc, access, addr, size, value, ud):
        off = addr - base
        if off == R_BSRR:
            apply(value & 0xFFFF, (value >> 16) & 0xFFFF)
        elif off == R_BRR:
            apply(0, value & 0xFFFF)
        elif off == R_ODR:
            cur = (lvl["scl"] << sb) | (lvl["sda"] << db)
            setm = value & ~cur
            rstm = (~value) & cur
            apply(setm & 0xFFFF, rstm & 0xFFFF)
        return True

    sim.uc.hook_add(UC_HOOK_MEM_WRITE, hook, begin=base, end=base + 0x18)
    return dev


# --- key helpers (active-low front-panel keys) ------------------------------
def key_press(sim, name):
    sim.set_input(KEYS[name], 0)     # pressed = pin pulled low

def key_release(sim, name):
    sim.set_input(KEYS[name], 1)     # released = pulled up

def keys_idle(sim):
    for n in KEYS:
        sim.set_input(KEYS[n], 1)
