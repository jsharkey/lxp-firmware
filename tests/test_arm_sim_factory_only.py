#!/usr/bin/env python3
"""
Factory-image-only tests on the arm_sim harness (tools/arm_sim.py).

These assert the same behavioural contracts as our firmware (see
tests/arm_sim_contract.py), but invoke the factory ceaa-07xx image's *actual*
relay-drive code by hard-coded address, with seeded state -- so the code here is
specific to the factory image and cannot be shared. Our side of each contract
lives in tests/test_arm_sim_self_only.py; both import the same contract tables,
so the factory oracle and our reimplementation are held to one identical spec.

Why these are not in the common black-box file: the relays are driven from the
factory's main control loop, which runs as an RTOS task the harness does not
schedule (docs/19), so they can't be reached purely by injecting a GPIO input.
Instead we call the genuine factory drive code directly with the state the RTOS
task would act on (the override path is self-contained -- no boot needed).

Usage (same style as test_arm_sim.py -- the image is a command-line argument, a
flat .bin; a .hex is rejected, convert it first with `make factory`):

    python3 tests/test_arm_sim_factory_only.py reference/com_flat.bin

The factory image is never committed (it is proprietary); with no image argument
the tests SKIP. Needs `pip install unicorn`.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_contract import (RELAY_OVERRIDE_TRUTH, RUN_STATES, NONRUN_STATES,
                              SAFETY_TELEMETRY, SAFETY_TELEMETRY_A, SAFETY_TELEMETRY_B)
from arm_sim_runner import Skip, run_tests

# Factory flat-.bin image under test. Set by the __main__ runner from argv.
_IMAGE = [None]


def _factory():
    path = _IMAGE[0]
    if not path:
        raise Skip("no factory image given (pass a flat .bin as the argument)")
    if not os.path.exists(path):
        raise Skip("factory image %s not found" % path)
    if is_intel_hex(path):
        raise ValueError("%s is an Intel .hex; pass a flat .bin -- convert it "
                         "first (`make factory` or tools/hex2bin.py)" % path)
    return ArmSim(path)


# --- factory relay drive: re-pin needed before these can run (docs/18) ------
# These two tests were written against docs/18's first relay analysis, which has
# since been retracted: the addresses they used -- the manual-mode flag
# `0x2000d0e4+0xa9`, the override command word `0x2000da6c`, and IR_STATE at
# `0x2000d0e4+0xa0` -- are the phantom addresses docs/18 now flags as *not
# materialized anywhere in the image* (the real IR_STATE byte is `0x2000a0d8+0x90`,
# docs/22/30). The "updaters" they called (`sub_08018a7c`, `sub_08016ec6`) are
# also not callable entry points: `sub_08016ec6` is a tail inside the 20-byte bit
# helper `sub_08016ebc`, and `sub_08018a7c` is a mid-function branch of the large
# decider `sub_08018518` (it reads `r10`/`sl` and faults when entered cold). The
# real relay deciders are big multi-input control functions (they read IR_STATE
# *and* the DSP grid/fault status, debounce counters and config enables), so they
# can't be exercised as the isolated updaters assumed here without seeding that
# whole context -- the "re-pin the relay state source" item docs/18 leaves open.
#
# Until that re-pin lands, these SKIP rather than assert against stale addresses
# (where they previously crashed / failed). The same override + working-mode
# contracts (RELAY_OVERRIDE_TRUTH / RUN_STATES / NONRUN_STATES) are still enforced
# on our implementation by tests/test_arm_sim_self_only.py, so the behaviour is
# covered; only the factory-oracle cross-check is paused.
_RELAY_REPIN = ("factory relay deciders need re-pinning (docs/18): the addresses "
                "these drove (0x2000d0e4+0xa0/0xa9, 0x2000da6c) are retracted "
                "phantoms and sub_08018a7c/sub_08016ec6 are not callable entry "
                "points -- see the comment above. Contract still enforced in "
                "test_arm_sim_self_only.py.")


def test_relay_override_drives_transfer_pins():
    """Manual/AutoTest relay override (docs/18): a command word drives PA12 (bit 1)
    and PB3 (bit 0) in manual mode, ignored otherwise. SKIPPED on the factory side
    pending a relay-decider re-pin (see above); enforced on ours in the self-only
    suite."""
    raise Skip(_RELAY_REPIN)


def test_relay_follows_working_mode():
    """The run-enable relay (PC6) is closed in a running operating mode and open in
    standby/fault/programming (docs/18). SKIPPED on the factory side pending a
    relay-decider re-pin (see above); enforced on ours in the self-only suite."""
    raise Skip(_RELAY_REPIN)


# --- safety-CPU telemetry -> Modbus input registers (docs/30, docs/33) ------
# The factory decodes the safety CPU's USART2 telemetry into its bank at
# 0x20009e54 (docs/33). The harness does not run the DMA+RTOS ingest task, so we
# present the telemetry already in that bank -- where the factory's own register
# getter reads it -- and read it back over the dongle. The getter + scaling +
# Modbus serialisation exercised are entirely the factory's. (arm_sim_safety.py.)
FAC_SAFETY_BANK = 0x20009e54


def _safety_factory():
    from arm_sim_modbus import ModbusDongle
    from arm_sim_safety import FakeSafetyCpu
    sim = _factory()
    return FakeSafetyCpu(sim, FAC_SAFETY_BANK, ModbusDongle(sim))


def test_safety_cpu_telemetry_reaches_modbus():
    """Safety-CPU telemetry (grid/PV/bus V, frequency, radiator temps, inverter
    current) must reach the dongle's Modbus input registers with the right
    register and scaling, and must TRACK CHANGES over time (a second, fluctuated
    snapshot reads back its new values -- the register image is live, not a
    one-shot cache). The factory image is the oracle for the shared telemetry
    contract (SAFETY_TELEMETRY); our side is in test_arm_sim_self_only.py."""
    fake = _safety_factory()
    for label, snapshot in (("A", SAFETY_TELEMETRY_A), ("B", SAFETY_TELEMETRY_B)):
        fake.send(snapshot)
        for name, raw in snapshot.items():
            _off, ir, _sc = SAFETY_TELEMETRY[name]
            exp = fake.expected(name, raw)
            got = fake.served(name)
            assert got == exp, ("factory snapshot %s: %s -> IR %d = %r, expected "
                                "%r (raw %d)" % (label, name, ir, got, exp, raw))


# --- per-pack battery telemetry on the undocumented 5000+ range (docs/34) ---
# Per-pack frames arrive on CAN as id = 0x400 | (subtype<<5) | pack_index; the
# parser sub_080205d4 stores them in a per-pack array (0x2000691c, stride 0x36)
# and marks the pack present (0x2000a770 / count 0x2000a8ae). The serializer
# routes INPUT registers 5000-5126 to a *separate* getter (sub_08020cc0) that
# serves that array -- 30 register slots per pack (bases 5000/5030/5060/5090),
# paged for >4 packs. This range is undocumented and ABOVE the IR 0-239 sweep
# that first concluded "no per-pack register" (docs/34), so it was missed.
def _inject_pack(bat, pack, subtype, data8):
    bat.send(0x400 | (subtype << 5) | (pack & 0x1F), bytes(data8))


def test_per_pack_telemetry_reaches_modbus():
    """Per-pack battery telemetry DOES reach the dongle -- on undocumented input
    registers 5000+ (docs/34). Inject per-pack CAN frames (id 0x400|sub<<5|pack)
    for two packs, and read them back over the dongle: pack 0 in the 5000 block,
    pack 1 in the 5030 block, with the fields in frame order (reg 5000 = pack-0
    subtype-0 bytes[0:2], 5001 = bytes[2:4], 5004 = subtype-1 bytes[0:2]). A
    second, changed snapshot must read back its new values (live, not cached).
    Factory-only: this is a factory superset our build does not implement."""
    import struct as _s
    from arm_sim_modbus import ModbusDongle
    from arm_sim_can import CanBattery

    def snapshot(p0s0_a, p0s0_b, p0s1, p1s0):
        sim = _factory()
        bat = CanBattery(sim)
        mb = ModbusDongle(sim)
        bat.send_soc_soh(77, 96)                       # keep the aggregate block alive
        _inject_pack(bat, 0, 0, _s.pack("<HH", p0s0_a, p0s0_b) + b"\x00\x00\x00\x00")
        _inject_pack(bat, 0, 1, _s.pack("<H", p0s1) + b"\x00" * 6)
        _inject_pack(bat, 1, 0, _s.pack("<H", p1s0) + b"\x00" * 6)
        bat.settle()
        return mb.read_input(5000, 8), mb.read_input(5030, 8)

    p0, p1 = snapshot(0x1234, 0xABCD, 0x5678, 0x9ABC)
    assert p0[0] == 0x1234, "pack0 subtype0[0:2] -> IR 5000 = %r" % (p0[0],)
    assert p0[1] == 0xABCD, "pack0 subtype0[2:4] -> IR 5001 = %r" % (p0[1],)
    assert p0[4] == 0x5678, "pack0 subtype1[0:2] -> IR 5004 = %r" % (p0[4],)
    assert p1[0] == 0x9ABC, "pack1 subtype0[0:2] -> IR 5030 = %r" % (p1[0],)

    # Live, not cached: a changed snapshot reads back the new values.
    q0, _q1 = snapshot(0x1111, 0x2222, 0x3333, 0x4444)
    assert q0[0] == 0x1111 and q0[1] == 0x2222, \
        "per-pack registers did not track a change: IR 5000/5001 = %r" % (q0[:2],)


# --- zero-dependency runner (same invocation style as test_arm_sim.py) ------
def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        _IMAGE[0] = args[0]
    return run_tests("Factory-image-only tests", _IMAGE[0] or "<none>", globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
