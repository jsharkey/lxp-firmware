#!/usr/bin/env python3
"""Shared USART3 RX demux contract -- the SAME spec, factory-vs-ours (docs/39 T09).

The ARM does NOT parse the DSP's 0x49 telemetry on USART3; that wire's RX is a
Modbus slave (func 03/04/06/10) + DSP bootloader (func 21/22/23) demux. We prove
it two ways and check they agree:
  * factory: drive the real USART3 RX byte handler (sub_0801c3e6, buffer
    0x20007490) with the first two frame bytes and see whether a frame starts
    assembling (index reaches 2) or is dropped (<2).
  * ours:   inv_dsp_rx_classify(first, func, dev_addr) -> {REJECT, MODBUS, BOOTLOADER}.
A 0x49-SOF type-1 telemetry frame is REJECTED by both (its first byte != our
address, and 0x01 is not a valid function) -- so neither consumes it.
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

REJECT, MODBUS, BOOTLOADER = 0, 1, 2
DEV_ADDR = 1

# (label, first_byte, func_byte, expected_class)
RX_VECTORS = [
    ("addr+func03 read-holding",   DEV_ADDR, 0x03, MODBUS),
    ("addr+func04 read-input",     DEV_ADDR, 0x04, MODBUS),
    ("addr+func06 write-single",   DEV_ADDR, 0x06, MODBUS),
    ("addr+func10 write-multi",    DEV_ADDR, 0x10, MODBUS),
    ("broadcast(0)+func03",        0x00,     0x03, MODBUS),
    ("addr+func21 bootloader",     DEV_ADDR, 0x21, BOOTLOADER),
    ("addr+func22 bootloader",     DEV_ADDR, 0x22, BOOTLOADER),
    ("addr+func23 bootloader",     DEV_ADDR, 0x23, BOOTLOADER),
    ("0x49 telemetry SOF",         0x49,     0x01, REJECT),   # the DSP 0x49 frame
    ("addr+type-1 (0x01)",         DEV_ADDR, 0x01, REJECT),
    ("addr+invalid func 0x02",     DEV_ADDR, 0x02, REJECT),
    ("wrong address",              0x02,     0x03, REJECT),
]

# factory USART3 RX byte handler + buffer (RE: docs/wiring/ARM-USART3-DSP)
FAC_RX = 0x0801c3e6
FAC_BUF = 0x20007490
FAC_IDX = FAC_BUF + 0x44e
FAC_ADDR_BYTE = 0x2000a0d8 + 0x9b


class FactoryBackend:
    name = "factory"

    def __init__(self, image, symbols=None):
        self.image = image
        self.symbols = symbols or os.path.join(
            os.path.dirname(__file__), "..", "reference", "symbols.csv")

    def available(self):
        try:
            from emu import Emu  # noqa: F401
            return os.path.exists(self.image)
        except Exception:
            return False

    def accepts(self, first, func):
        """Feed the first two bytes; a frame starts assembling iff the index
        reaches 2 (both bytes accepted). Fresh emulator per probe."""
        from emu import Emu
        e = Emu(self.image, self.symbols)
        e.uc.mem_write(FAC_ADDR_BYTE, bytes([DEV_ADDR]))
        e.call(FAC_RX, (first,))
        e.call(FAC_RX, (func,))
        return struct.unpack("<H", e.rbytes(FAC_IDX, 2))[0] == 2


class OursBackend:
    name = "ours"

    def __init__(self, bin_path, elf_path):
        self.bin_path = bin_path
        self.elf_path = elf_path
        self._sim_cache = []

    def _sim(self):
        from arm_sim import ArmSim, load_symbols_nm
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        if not self._sim_cache:
            self._sim_cache.append(ArmSim(self.bin_path, load_symbols_nm(self.elf_path)))
        return self._sim_cache[0]

    def available(self):
        try:
            self._sim()
            return True
        except Exception:
            return False

    def classify(self, first, func):
        sim = self._sim()
        return sim.call("inv_dsp_rx_classify", (first, func, DEV_ADDR)) & 0xFF
