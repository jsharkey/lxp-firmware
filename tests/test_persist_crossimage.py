#!/usr/bin/env python3
"""
Cross-image settings persistence -- proof the on-flash config format is
compatible in BOTH directions:

  * a value persisted by *our* firmware is read back correctly by the *factory*
    firmware, and
  * a value persisted by the *factory* is read back correctly by *ours*.

Each case boots one image, writes HR 101 (ChargeCurr) over the Modbus dongle,
lets it journal to the SPI config flash, then COLD-BOOTS the *other* image whose
only carry-over is that same flash device, and reads the register back. If the
record format (slot/offset, CRC, marker, scaling, ring layout) weren't
byte-compatible, one side would read a default or garbage.

Needs BOTH images: ours (built) and the factory flat .bin. SKIPs if either is
missing, so it is a no-op where the proprietary image isn't present. Requires
`pip install unicorn`.

Usage: python3 tests/test_persist_crossimage.py [OURS.bin] [FACTORY.bin]
  defaults: build/firmware.bin  and  $LXP_FACTORY_BIN or reference/ceaa-07xx_vE_260214.bin
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_runner import Skip, run_tests

_OURS = [None]
_FACTORY = [None]

HR_CHARGE_CURR = 101
CONFIG_END = 0xC000           # the six 8 KB config slots, 0x0000-0xBFFF
SETTLE = 15_000_000           # budget for the (debounced) flush at fast SysTick
SYSTICK = 2000


def _images():
    ours = _OURS[0] or os.environ.get("LXP_SIM_IMAGE") or "build/firmware.bin"
    fac = _FACTORY[0] or os.environ.get("LXP_FACTORY_BIN") or "reference/ceaa-07xx_vE_260214.bin"
    for p in (ours, fac):
        if not os.path.exists(p):
            raise Skip("cross-image test needs both images; missing %s" % p)
        if is_intel_hex(p):
            raise ValueError("%s is an Intel .hex; pass a flat .bin (make factory)" % p)
    return ours, fac


def _boot_budget(path):
    """Pre-roll instructions before the dongle transacts. Our compact build
    paints a bit-banged LCD splash and needs a long boot to serve Modbus; the
    large factory flat image boots fast, and a long pre-roll would let its
    debounced config flush race our write. Size tells them apart."""
    return 1_000_000 if os.path.getsize(path) > 0x40000 else 5_000_000


def _boot_write(image, dev, reg, value):
    """Boot `image` (fresh CPU+RAM), write reg=value over Modbus, and run until
    it is journaled to flash. `dev` None attaches a fresh factory-provisioned
    config flash; otherwise the carried-over device is reused (a cold boot that
    keeps only the flash). Returns (echo, flash_device, flushed?)."""
    from arm_sim_modbus import ModbusDongle
    sim = ArmSim(image)
    dev = sim.attach_config_flash() if dev is None else sim.attach_spi_flash(flash=dev)
    mb = ModbusDongle(sim, systick=SYSTICK, boot_insn=_boot_budget(image))
    baseline = bytes(dev.mem[:CONFIG_END])
    echo = mb.write_single(reg, value)
    used = 0
    while used < SETTLE and bytes(dev.mem[:CONFIG_END]) == baseline:
        sim.run(1_000_000)
        used += 1_000_000
    return echo, dev, bytes(dev.mem[:CONFIG_END]) != baseline


def _cold_read(image, dev, reg):
    """Cold-boot `image` (fresh CPU+RAM) on the carried-over flash; read reg."""
    from arm_sim_modbus import ModbusDongle
    sim = ArmSim(image)
    sim.attach_spi_flash(flash=dev)
    mb = ModbusDongle(sim, systick=SYSTICK, boot_insn=_boot_budget(image))
    return mb.read_holding(reg)


def test_ours_persists_factory_reads():
    """A unit that shipped with the factory firmware (so slot 0 holds a full,
    valid factory config record) gets our firmware; we change ChargeCurr; it is
    later re-flashed to factory. The factory must read our new value.

    We model that exactly: the factory first establishes its record, then OUR
    firmware does a read-modify-write (changing only ChargeCurr, preserving every
    other factory field), then the factory cold-boots and reads it back."""
    ours, factory = _images()
    # 1) factory establishes a real, fully-populated slot-0 record
    _, dev, seeded = _boot_write(factory, None, HR_CHARGE_CURR, 10)
    assert seeded, "factory did not establish a baseline config record"
    # 2) our firmware changes ChargeCurr (read-modify-write of that record)
    echo, dev, flushed = _boot_write(ours, dev, HR_CHARGE_CURR, 55)
    assert echo == 55 and flushed, \
        "ours did not persist ChargeCurr (echo=%r flushed=%s)" % (echo, flushed)
    # 3) back on factory firmware: our change must be visible
    got = _cold_read(factory, dev, HR_CHARGE_CURR)
    assert got == [55], \
        "factory read %r from ours-modified flash, not [55]" % got


def test_factory_persists_ours_reads():
    """The factory firmware writes ChargeCurr; our firmware reads it after a cold
    boot off the same flash -- our loader accepts a genuine factory record."""
    ours, factory = _images()
    echo, dev, flushed = _boot_write(factory, None, HR_CHARGE_CURR, 44)
    assert echo == 44 and flushed, \
        "factory did not persist ChargeCurr (echo=%r flushed=%s)" % (echo, flushed)
    got = _cold_read(ours, dev, HR_CHARGE_CURR)
    assert got == [44], \
        "ours read %r from factory-written flash, not [44]" % got


def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) >= 1:
        _OURS[0] = args[0]
    if len(args) >= 2:
        _FACTORY[0] = args[1]
    return run_tests("Cross-image persistence",
                     "%s <-> %s" % (_OURS[0] or "ours", _FACTORY[0] or "factory"),
                     globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
