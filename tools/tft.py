#!/usr/bin/env python3
"""
tft — an emulator model of the factory HMI's graphic LCD, for tools/arm_sim.py.

The factory ARM image drives a small **MIPI-DCS color TFT** (ST77xx/ILI-class),
not over SPI1 (that bus is the config NOR flash) but **bit-banged 4-wire serial
on GPIOB**:

    PB12 = SCLK   PB13 = SDA   PB14 = DC (0=command, 1=data)   PB15 = /CS

(docs/16 previously listed PB12/13/15 as a "status-LED bank"; dynamic RE shows
they are the LCD bus — see docs/23.) Bytes are shifted MSB-first; the command
primitive is `sub_080114d2(rs, byte)` and the byte-banger `sub_08011dd0`.

The panel is **128x160, 1 byte per pixel**. The firmware draws straight into the
controller's GRAM with MIPI-DCS windowed writes (CASET 0x2A / RASET 0x2B /
RAMWR 0x2C), so there is no full RAM framebuffer — this model keeps the GRAM.

`attach_tft(sim)` hooks GPIOB writes on an ArmSim and returns a Tft whose `.gram`
(160 rows x 128 cols of raw pixel bytes) is exactly what the running firmware has
drawn. `mono(gram)` renders it the way the physical panel reads: 2-level
monochrome (the dominant value is the background). Pure model; decodes by
bit/nibble order, not timing. No hardware.
"""
import numpy as np
from arm_sim import GPIO, R_BSRR, R_BRR
from unicorn import UC_HOOK_MEM_WRITE

GB = GPIO["B"]
PIN_CLK, PIN_DATA, PIN_DC, PIN_CS = 12, 13, 14, 15
W, H = 128, 160            # columns (X), rows (Y)


class Tft:
    """ST77xx-class GRAM model fed one serial byte at a time (tagged cmd/data)."""
    def __init__(self):
        self.clk = self.data = self.dc = 0
        self.cs = 1
        self.bits = 0
        self.cur = 0
        self.gram = np.zeros((H, W), dtype=np.uint8)
        self.mode = None
        self.params = []
        self.x0 = 0; self.x1 = W - 1
        self.y0 = 0; self.y1 = H - 1
        self.x = 0; self.y = 0
        self.madctl = 0
        self.nbytes = 0

    def _byte(self, dc, v):
        self.nbytes += 1
        if dc == 0:                       # command
            if v == 0x2A:   self.mode = "CASET"; self.params = []
            elif v == 0x2B: self.mode = "RASET"; self.params = []
            elif v == 0x2C: self.mode = "RAMWR"; self.x = self.x0; self.y = self.y0
            elif v == 0x36: self.mode = "MADCTL"; self.params = []
            else:           self.mode = "PARAMS"
        else:                             # data
            if self.mode == "CASET":
                self.params.append(v)
                if len(self.params) == 4:
                    self.x0 = (self.params[0] << 8) | self.params[1]
                    self.x1 = (self.params[2] << 8) | self.params[3]
                    self.mode = None
            elif self.mode == "RASET":
                self.params.append(v)
                if len(self.params) == 4:
                    self.y0 = (self.params[0] << 8) | self.params[1]
                    self.y1 = (self.params[2] << 8) | self.params[3]
                    self.mode = None
            elif self.mode == "MADCTL":
                self.madctl = v; self.mode = None
            elif self.mode == "RAMWR":
                if 0 <= self.y < H and 0 <= self.x < W:
                    self.gram[self.y, self.x] = v
                self.x += 1
                if self.x > self.x1:
                    self.x = self.x0; self.y += 1
            # PARAMS: other commands' parameters are ignored

    def _line(self, pin, level):
        if pin == PIN_CLK:
            if level and not self.clk and self.cs == 0:   # sample on rising edge
                self.cur = ((self.cur << 1) | self.data) & 0xFF
                self.bits += 1
                if self.bits == 8:
                    self._byte(self.dc, self.cur); self.bits = 0; self.cur = 0
            self.clk = level
        elif pin == PIN_DATA:
            self.data = level
        elif pin == PIN_DC:
            self.dc = level
        elif pin == PIN_CS:
            if level and not self.cs:                      # deselect resets the shift state
                self.bits = 0; self.cur = 0
            self.cs = level

    def apply(self, set_mask, reset_mask):
        # DC/DATA/CS settle before the clock edge that samples them
        for pin in (PIN_CS, PIN_DC, PIN_DATA, PIN_CLK):
            if (set_mask >> pin) & 1:   self._line(pin, 1)
            if (reset_mask >> pin) & 1: self._line(pin, 0)


def attach_tft(sim):
    """Attach a Tft to an ArmSim, driven from GPIOB BSRR/BRR writes. Returns it."""
    t = Tft()

    def hook(uc, access, addr, size, value, ud):
        off = addr - GB
        if off == R_BSRR:
            t.apply(value & 0xFFFF, (value >> 16) & 0xFFFF)
        elif off == R_BRR:
            t.apply(0, value & 0xFFFF)
        return True

    sim.uc.hook_add(UC_HOOK_MEM_WRITE, hook, begin=GB, end=GB + 0x18)
    return t


def mono(gram, invert=False):
    """Render the GRAM as the physical monochrome panel reads it: the dominant
    pixel value is the background (white); everything else is ink (black).
    Returns a uint8 HxW image (0 or 255)."""
    bg = int(np.bincount(gram.ravel()).argmax())
    img = np.where(gram == bg, 255, 0).astype(np.uint8)
    return (255 - img) if invert else img
