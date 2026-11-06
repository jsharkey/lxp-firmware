#!/usr/bin/env python3
"""
Cross-image settings persistence -- the on-flash config format is byte-compatible
in BOTH directions, over the pinned settings table (docs/23, task T03).

The table (slot / offset / width / scale per holding register) lives in
`settings_persist_contract.py` and mirrors the C side `include/inv/settings_map.h`.
A wrong offset, width or scale on either side makes a value read back wrong, so
these tests are the oracle that pins the table -- in particular the slot-5
power-command block, whose fields are 1 byte wide, not the "2B" docs/23 first
recorded (settled here; docs/23 corrected).

Two directions, shaped around hard harness constraints (docs/23 "Harness note"):

  * ours -> flash, FULL TABLE, byte-exact to the factory layout. Our firmware
    writes all 62 registers in one boot; we read the record bytes back and assert
    each field is at the table's slot/offset/width, scaled as the factory stores
    it, and -- for one register per storage class -- byte-identical to the
    factory's own record for that value. (A full-table *live* factory read-back is
    blocked: the factory's RTOS re-journals on boot and wedges the dongle whenever
    it boots on a device we have written -- a T02 dependency.)

  * factory -> ours, ONE REGISTER PER STORAGE CLASS, live. The factory writes a
    value (its own writer, one write per boot -- a settings write blocks further
    dongle service until reboot; reads are unaffected), ours cold-boots on that
    flash and reads it back. Covers one register per distinct (slot, width, scale)
    class -- our loader decoding a genuine factory record.

Needs BOTH images: ours (built) and the factory flat .bin. SKIPs if either is
missing. Requires `pip install unicorn`.

Usage: python3 tests/test_persist_crossimage.py [OURS.bin] [FACTORY.bin]
  defaults: build/firmware.bin  and  $LXP_FACTORY_BIN or reference/ceaa-07xx_vE_260214.bin
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim import ArmSim, is_intel_hex
from arm_sim_runner import Skip, run_tests
from settings_persist_contract import SETTINGS_MAP

_OURS = [None]
_FACTORY = [None]

CONFIG_END = 0xC000           # the six 8 KB config slots, 0x0000-0xBFFF
SETTLE = 20_000_000           # budget for the (debounced) flush at fast SysTick
SYSTICK = 2000

WANT  = {reg: test for (reg, _s, _o, _w, _sc, test) in SETTINGS_MAP}
SLOT  = {reg: slot for (reg, slot, _o, _w, _sc, _t) in SETTINGS_MAP}
OFF   = {reg: off  for (reg, _s, off, _w, _sc, _t) in SETTINGS_MAP}
WIDTH = {reg: w    for (reg, _s, _o, w, _sc, _t) in SETTINGS_MAP}
SCALE = {reg: sc   for (reg, _s, _o, _w, sc, _t) in SETTINGS_MAP}
REGS = [reg for (reg, _s, _o, _w, _sc, _t) in SETTINGS_MAP]
SLOT_REGION = 0x2000

# HR 21 (FuncEn) reads back with an extra capability bit the factory always
# reports (written | 0x200); our stored bits must all survive, but the read is
# not an exact echo. See docs/31 (factory quirk) / docs/23. For these the test
# asserts (got & want) == want instead of equality.
READ_OR_MASK = {21}


def _value_ok(reg, want, got):
    if got is None:
        return False
    if reg in READ_OR_MASK:
        return (got & want) == want
    return got == want
# one register per distinct (slot, width, scale) storage class, for the
# factory->ours direction (which is limited to one write per boot).
_CLASS = {}
for reg, slot, off, w, sc, test in SETTINGS_MAP:
    _CLASS.setdefault((slot, w, sc), reg)
CLASS_REGS = sorted(_CLASS.values())


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
    """Pre-roll before the dongle transacts. Our compact build paints an LCD
    splash and needs a long boot to serve Modbus; the big factory flat image
    boots fast, and a long pre-roll would let its debounced flush race us."""
    return 1_000_000 if os.path.getsize(path) > 0x40000 else 5_000_000


def _mb(image, dev, payloads=None):
    from arm_sim_modbus import ModbusDongle
    sim = ArmSim(image)
    if dev is None:
        dev = sim.attach_config_flash(payloads=payloads)
    else:
        dev = sim.attach_spi_flash(flash=dev)
    return sim, dev, ModbusDongle(sim, systick=SYSTICK, boot_insn=_boot_budget(image))


def _flush(sim, dev, lo=0, hi=CONFIG_END):
    """Run until the watched flash window [lo:hi) changes (a journal landed), up
    to SETTLE. Watching a single slot's region matters because the factory
    flushes slot 0 first on a write; a slot-5 setting lands a few M later."""
    base = bytes(dev.mem[lo:hi])
    used = 0
    while used < SETTLE and bytes(dev.mem[lo:hi]) == base:
        sim.run(1_000_000)
        used += 1_000_000
    return bytes(dev.mem[lo:hi]) != base


def _write_one(image, dev, reg, val):
    sim, dev, mb = _mb(image, dev)
    echo = mb.write_single(reg, val)
    lo = SLOT[reg] * SLOT_REGION
    flushed = _flush(sim, dev, lo, lo + SLOT_REGION)   # wait for THIS slot
    return dev, echo, flushed


def _write_all(image, dev, pairs, payloads=None):
    """Boot once, write every (reg,val), journal. Returns (dev, bad, flushed)."""
    sim, dev, mb = _mb(image, dev, payloads=payloads)
    bad = []
    for reg, val in pairs:
        echo = mb.write_single(reg, val)
        if echo != val:
            bad.append((reg, val, echo))
    flushed = _flush(sim, dev)
    return dev, bad, flushed


def _seed_dev(image, reg, val, slot):
    """On a FRESH blank flash, write `reg`=`val` so the factory serializes its
    whole settings struct for `slot`, journal it, and return (dev, echo). One
    write on a fresh device is the reliable path -- the factory's
    one-write-per-boot and re-journal-on-boot limits only bite when reusing a
    populated device."""
    sim, dev, mb = _mb(image, None)
    echo = mb.write_single(reg, val)
    lo = slot * SLOT_REGION
    _flush(sim, dev, lo, lo + SLOT_REGION)
    return dev, echo


def _payload(dev, slot):
    """The newest valid record's 250-byte payload in `slot`, or None."""
    base = slot * SLOT_REGION
    for a in range(base + SLOT_REGION - 0x100, base - 1, -0x100):
        rec = bytes(dev.mem[a:a + 0x100])
        if rec[0xFF] == 0xA5:
            return rec[0:0xFA]
    return None


def _field_bytes(payload, off, width):
    return payload[off] if width == 1 else (payload[off] | (payload[off + 1] << 8))


def _read_regs(image, dev, regs):
    """Read `regs` grouped into 40-register Modbus reads. One group per FRESH
    boot: the factory re-journals its loaded config early in boot, and that
    internal write blocks the dongle after the first transaction, so only the
    first read per boot is served. A cold boot per group keeps each read the
    first. (Our firmware is polled and would serve all in one boot; booting per
    group is just harmless extra boots for it.)"""
    out = {}
    for g in range(0, 160, 40):
        want = [r for r in regs if g <= r < g + 40]
        if not want:
            continue
        _sim, _dev, mb = _mb(image, dev)
        block = mb.read_holding(g, 40)
        if block is None:
            continue
        for r in want:
            out[r] = block[r - g]
    return out


def test_ours_writes_the_factory_byte_layout_full():
    """Full table, ours -> flash, byte-exact to the factory layout.

    Our firmware writes all 62 pinned registers and journals them; we then read
    the record bytes back and assert each field sits at the table's
    slot/offset/width with the value scaled as the factory stores it (x10 for the
    current set). For one register per (slot, width, scale) storage class we also
    assert our bytes are **identical to the factory's own record bytes** for the
    same value (the factory writes that register on a fresh device -- reliable),
    so the layout is anchored to the factory, not just to our own table.

    Why bytes and not a factory read-back of the whole table: in this harness the
    factory's RTOS re-journals its config early in boot, and that internal write
    wedges the dongle for the rest of the boot whenever it boots on a device our
    firmware has written -- so the factory cannot be driven to read our 62-register
    flash. The per-class *live* round-trip in the other direction
    (`test_factory_persists_ours_reads_by_class`) covers factory<->ours decode; a
    full-table live ours->factory read-back is blocked on T02 (factory RTOS in the
    sim). Bytes + per-class factory anchor is the reliable equivalent here."""
    ours, factory = _images()
    dev, bad, flushed = _write_all(ours, None, [(r, WANT[r]) for r in REGS])
    assert not bad, "ours did not echo writes: %r" % bad[:8]
    assert flushed, "ours did not journal the settings to flash"
    p = {0: _payload(dev, 0), 5: _payload(dev, 5)}
    assert p[0] and p[5], "ours did not write both slot records"

    # (a) every field lands at the table's slot/offset/width, scaled as stored.
    wrong = []
    for reg, slot, off, w, sc, test in SETTINGS_MAP:
        exp = (test * sc) & (0xFF if w == 1 else 0xFFFF)
        got = _field_bytes(p[slot], off, w)
        if got != exp:
            wrong.append((reg, exp, got))
    assert not wrong, "ours stored wrong bytes (reg,exp,got): %r" % wrong

    # (b) cross-image anchor: one register per storage class is byte-identical to
    #     the factory's own record for the same value.
    anchor = []
    for reg in CLASS_REGS:
        slot, off, w, sc = SLOT[reg], OFF[reg], WIDTH[reg], SCALE[reg]
        fdev, echo = _seed_dev(factory, reg, WANT[reg], slot)
        assert echo == WANT[reg], "factory did not write HR %d (echo=%r)" % (reg, echo)
        fp = _payload(fdev, slot)
        if _field_bytes(fp, off, w) != _field_bytes(p[slot], off, w):
            anchor.append((reg, _field_bytes(fp, off, w), _field_bytes(p[slot], off, w)))
    assert not anchor, "ours != factory bytes at class anchors (reg,factory,ours): %r" % anchor


def test_factory_persists_ours_reads_by_class():
    """factory -> ours, one register per storage class. The factory writes a
    value (its own writer, one write per boot), ours cold-boots on that flash and
    must read it back -- proving our loader decodes a genuine factory record for
    each (slot, width, scale) class."""
    ours, factory = _images()
    results = []
    for reg in CLASS_REGS:
        val = WANT[reg]
        dev, echo, flushed = _write_one(factory, None, reg, val)
        assert echo == val and flushed, \
            "factory did not persist HR %d (echo=%r flushed=%s)" % (reg, echo, flushed)
        got = _read_regs(ours, dev, [reg]).get(reg)
        results.append((reg, val, got))
    bad = [(r, w, g) for (r, w, g) in results if not _value_ok(r, w, g)]
    assert not bad, "ours read wrong values from factory-written flash (reg,want,got): %r" % bad


def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) >= 1:
        _OURS[0] = args[0]
    if len(args) >= 2:
        _FACTORY[0] = args[1]
    return run_tests("Cross-image persistence (pinned table)",
                     "%s <-> %s" % (_OURS[0] or "ours", _FACTORY[0] or "factory"),
                     globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
