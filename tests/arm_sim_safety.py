#!/usr/bin/env python3
"""
A black-box "fake safety CPU" -- the redundant/safety MCU on the far end of the
ARM's USART2 link (docs/29, docs/30). It lets a test inject the live grid/PV/bus
telemetry that peer streams, and lets the firmware image serve it back out over
the dongle (USART3) as Modbus input registers -- exactly as a monitoring tool
would see it.

It names no firmware symbol of its own; it is pointed at a telemetry *bank* base
address (the factory's `0x20009e54`, or our build's equivalent by symbol) and
writes the decoded fields there, then reads them back through the real Modbus
getter. The field offsets, scales and register numbers are the shared contract
in arm_sim_contract.py (recovered in docs/33).

WHY INJECT AT THE BANK (not raw USART2 bytes): on the wire the safety CPU sends
an EG4 "type-1" big-endian frame (SOF 0x49, CRC-16/MODBUS; the per-tag record
layout is documented in docs/33). The factory assembles and parses that frame
via a DMA channel plus a scheduler task (`sub_080259d8`) that the arm_sim harness
does not run (it is a preemptive-RTOS task; a 6M-instruction loop never reaches
it, same reason the relay tests call their drive code directly -- docs/19). So,
like CanBattery presents a frame already sitting in the bxCAN FIFO mailbox where
the firmware's own consumer reads it, this presents the telemetry already decoded
into the bank where the firmware's own register getter reads it. The getter, the
scaling and the Modbus serialisation under test are entirely the firmware's.

The parse half (USART2 frame -> bank) is documented and separately validated in
docs/33; this exercises the serve half (bank -> scaled input register -> wire).
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim_contract import SAFETY_TELEMETRY, safety_served


class FakeSafetyCpu:
    """Stand-in for the safety CPU on USART2. Point it at a telemetry-bank base
    (factory `0x20009e54` by address, or our build's bank by symbol) and a
    ModbusDongle; `send()` publishes a telemetry snapshot, `served()` reads a
    field back through the firmware's real Modbus input-register path."""

    def __init__(self, sim, bank_base, modbus):
        self.sim = sim
        self.base = bank_base
        self.mb = modbus

    def send(self, values):
        """Publish a telemetry snapshot: {field: raw_value}. Each field is stored
        at its bank offset as a native little-endian u16 -- the exact shape the
        USART2 frame parser leaves behind (docs/33)."""
        for name, raw in values.items():
            off, _ir, _scale = SAFETY_TELEMETRY[name]
            self.sim.uc.mem_write(self.base + off, struct.pack("<H", raw & 0xFFFF))

    def served(self, name):
        """Read `name` back over the dongle (real getter + Modbus). Returns the
        input-register value, or None if no reply framed."""
        _off, ir, _scale = SAFETY_TELEMETRY[name]
        got = self.mb.read_input(ir)
        return got[0] if got else None

    @staticmethod
    def expected(name, raw):
        """The input-register value `raw` for `name` should be served as."""
        return safety_served(name, raw)
