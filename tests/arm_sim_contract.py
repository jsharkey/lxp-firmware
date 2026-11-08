"""Shared relay behaviour contracts that BOTH firmware images are held to.

The common black-box tests (test_arm_sim.py) run identical code against either
image. The relay behaviours cannot be reached as a pure black box -- the factory
drives them from an RTOS task the harness does not schedule (docs/19) -- so each
image is exercised through its own drive path:

  * test_arm_sim_self_only.py    -- our firmware, by symbol (src/relay.c)
  * test_arm_sim_factory_only.py -- the factory image, by address (ceaa-07xx)

Both import the tables below, so "the factory oracle and our firmware agree" is
guaranteed by each satisfying one shared spec -- parity by contract, rather than
a single test that compares the two internally.
"""

# --- manual / AutoTest relay override (docs/18) ----------------------------
# In manual/test mode a command word drives the AC transfer relays directly:
# bit1 -> PA12, bit0 -> PB3. Ignored entirely when not in manual mode.
#   (cmd, manual) -> (PA12, PB3)
RELAY_OVERRIDE_TRUTH = {
    (0, 1): (0, 0),
    (1, 1): (0, 1),
    (2, 1): (1, 0),
    (3, 1): (1, 1),
    (3, 0): (0, 0),   # override ignored outside manual mode
}

# --- working-mode run-enable relay (docs/18) -------------------------------
# PC6 is closed (1) iff the inverter is in a running operating mode
# (IR_STATE > PROGRAMMING = 2); open (0) in standby / fault / programming.
RUN_STATES    = (0x04, 0x10, 0x40, 0xC0)   # PV-ongrid, bat-ongrid, bat-offgrid, pv+bat-offgrid
NONRUN_STATES = (0x00, 0x01, 0x02)         # standby, fault, programming


# --- safety-CPU telemetry -> Modbus input registers (docs/30, docs/33) ------
# The redundant/"safety" CPU streams the live grid/PV/bus measurements to the
# ARM over USART2; the ARM decodes them into its telemetry bank (0x20009e54,
# docs/33) and serves them to the dongle as input registers. This table is the
# contract both images are held to: a decoded telemetry field lands at a fixed
# bank offset (native little-endian u16) and is served on a given input register
# with a fixed scale.
#
#   field -> (bank byte offset, input register, served = round(raw * scale))
#
# Most fields are served verbatim; the inverter-current RMS is scaled x10 and the
# radiator temperatures /10 by the factory getter (sub_0803289c) -- our firmware
# must reproduce the same scales. Offsets/scales were recovered by sweeping the
# real getter over every register (docs/33).
SAFETY_TELEMETRY = {
    # field       off    IR   scale
    "pv1":       (0x4c,   1,  1),    # PV1 voltage        0.1 V
    "pv2":       (0x4e,   2,  1),    # PV2 voltage        0.1 V
    "grid_r":    (0x20,  12,  1),    # grid voltage R     0.1 V
    "grid_s":    (0x28,  13,  1),    # grid voltage S     0.1 V
    "grid_t":    (0xb6,  14,  1),    # grid voltage T     0.1 V
    "freq":      (0x5e,  15,  1),    # grid frequency     0.01 Hz
    "iinv":      (0x24,  18, 10),    # inverter current   served x10
    "veps_r":    (0x22,  20,  1),    # EPS voltage R      0.1 V
    "feps":      (0x60,  23,  1),    # EPS frequency      0.01 Hz
    "vbus1":     (0x0e,  38,  1),    # BUS 1 voltage      0.1 V
    "vbus2":     (0x10,  39,  1),    # BUS 2 voltage      0.1 V
    "vbus_p":    (0x12, 120,  1),    # half-BUS voltage   0.1 V
    "gen_freq":  (0x62, 122,  1),    # generator freq     0.01 Hz
    "t_rad1":    (0x1e,  65,  0.1),  # radiator temp 1    served /10
    "t_rad2":    (0x1c,  66,  0.1),  # radiator temp 2    served /10
    "batv_inv":  (0x0a, 107,  1),    # inverter batt V    0.1 V (verbatim)
    "pf":        (0xaa,  19,  1),    # power factor       raw 0-2000 (verbatim, IR019-PF.md)
}


def safety_served(field, raw):
    """The input-register value a given raw (bank) telemetry value is served as."""
    _off, _ir, scale = SAFETY_TELEMETRY[field]
    return int(round(raw * scale))


# Two telemetry snapshots. Set B is a small fluctuation of set A (a few tenths of
# a volt / 0.01 Hz, a degree) so a test can prove *changing* values propagate --
# the register image is not a one-shot cache. Raw bank units (pre-scale); temps
# and iinv are chosen as clean multiples so the scaled result is exact.
SAFETY_TELEMETRY_A = {
    "pv1": 3201, "pv2": 3180, "grid_r": 2401, "grid_s": 2402, "grid_t": 2403,
    "freq": 5999, "iinv": 150, "veps_r": 2400, "feps": 6000, "vbus1": 3900,
    "vbus2": 3901, "vbus_p": 1950, "gen_freq": 5998, "t_rad1": 350, "t_rad2": 360,
    "batv_inv": 530, "pf": 950,
}
SAFETY_TELEMETRY_B = {
    "pv1": 3195, "pv2": 3188, "grid_r": 2405, "grid_s": 2399, "grid_t": 2410,
    "freq": 6001, "iinv": 152, "veps_r": 2402, "feps": 5997, "vbus1": 3912,
    "vbus2": 3889, "vbus_p": 1948, "gen_freq": 6002, "t_rad1": 360, "t_rad2": 350,
    "batv_inv": 525, "pf": 1050,
}


# --- RTC wall-clock calendar walk (docs/36) --------------------------------
# Both firmwares keep a 7-byte software calendar advanced one second at a time
# (ours src/rtc/rtc.c; factory sub_08018bc0). Forcing the clock and walking it
# forward must carry sec->min->hour->day->month->year with the right
# days-in-month and leap-year handling. Each vector:
#   (label, start (sec,min,hour,day,month,year), +seconds, expected (same shape))
# `year` is offset from 2000. Driven via ArmSim.set_rtc()/advance_rtc() in both
# test_arm_sim_self_only.py (ours, by symbol) and test_arm_sim_factory_only.py
# (factory, by address) -- one spec, both images.
RTC_WALK = [
    ("tick +1s",             (0, 0, 0, 1, 1, 24),    1, (1, 0, 0, 1, 1, 24)),
    ("minute carry",         (58, 0, 0, 1, 1, 24),   4, (2, 1, 0, 1, 1, 24)),
    ("hour carry",           (58, 59, 0, 1, 1, 24),  4, (2, 0, 1, 1, 1, 24)),
    ("day carry",            (58, 59, 23, 1, 1, 24), 4, (2, 0, 0, 2, 1, 24)),
    ("30-day month -> next", (58, 59, 23, 30, 4, 24),4, (2, 0, 0, 1, 5, 24)),
    ("non-leap Feb -> Mar",  (58, 59, 23, 28, 2, 23),4, (2, 0, 0, 1, 3, 23)),
    ("leap Feb 28 -> Feb 29",(58, 59, 23, 28, 2, 24),4, (2, 0, 0, 29, 2, 24)),
    ("leap Feb 29 -> Mar",   (58, 59, 23, 29, 2, 24),4, (2, 0, 0, 1, 3, 24)),
    ("year roll",            (58, 59, 23, 31, 12, 24),4,(2, 0, 0, 1, 1, 25)),
]


def check_live_clock(sim, master):
    """Shared check that an image's Modbus time registers are a LIVE read of the
    internal RTC, not an echo of the last write. `sim` must already be
    configure_rtc()'d; `master` is the Modbus master class for the image's port
    (ModbusDongle on UART5 for ours; ModbusDsp on USART3 for the factory). Flow:
    boot the master, set a time over HR 12-14, drive the RTC forward with
    sim.advance_rtc() (the firmware's own tick), and confirm a read-back reflects
    the ADVANCED time -- which an echo of the written value could not. Used by
    both test_arm_sim_self_only.py and test_arm_sim_factory_only.py, one spec.
    """
    yr, mon, day, hr, mn, sec = 24, 3, 15, 14, 30, 45      # 2024-03-15 14:30:45
    mb = master(sim)
    mb.write_single(12, yr | (mon << 8))
    mb.write_single(13, day | (hr << 8))
    mb.write_single(14, mn | (sec << 8))

    def read():
        for _ in range(6):                   # tolerate a transient missed reply
            g = mb.read_holding(12, 3)
            if g:
                return (g[0] & 0xFF, g[0] >> 8, g[1] & 0xFF, g[1] >> 8,
                        g[2] & 0xFF, g[2] >> 8)
        return None

    before = read()
    assert before == (yr, mon, day, hr, mn, sec), \
        "time set/read-back = %r, expected %r" % (before, (yr, mon, day, hr, mn, sec))

    sim.advance_rtc(75)                       # 14:30:45 + 75 s -> 14:32:00
    after = read()
    assert after == (24, 3, 15, 14, 32, 0), \
        "after advancing 75 s the clock read %r, expected 14:32:00 (2024-03-15)" % (after,)
    assert after != before, \
        "clock did not advance on read -- the time registers are a static echo, not live"


# --- firmware-update / enter-bootloader contract (docs/43) ------------------
# The external dongle drives firmware updates of the inverter's chips over the
# EG4 Modbus link, but it is only a transparent conduit (docs/26): the ARM half
# is cooperative. For the DSP and peers the ARM is the *master* that drives them
# into their loader (the 0x21/0x22/0x23 "EDSN" protocol, docs/05). For its OWN
# update the ARM must reboot itself into its bootloader: the dongle's "restart
# inverter" command -- ResetSetting (holding reg 11) bit 7, InvReboot, in the EG4
# spec -- makes the firmware request an ARM system reset, and on a bootloader+App
# part (07-series 12000XP / 18kPV / 6000XP) that reset hands control to the
# bootloader at 0x08000000, below the App's own vector table. That is "enter
# flashing mode."
#
# Like the relays, neither image's reboot can be reached as a pure black box: the
# factory runs the ResetSetting consumer from an RTOS task the cold harness does
# not schedule, and its dongle register writes are gated too (docs/19/26). So
# each image is driven through its own path and held to this one contract:
#   * our firmware  -- the InvReboot Modbus write it implements (black box)
#   * the factory   -- its NVIC_SystemReset site, executed by address
# The shared assertion: the firmware writes VECTKEY(0x05FA)|SYSRESETREQ to
# SCB->AIRCR -- it asks the core to reset into the bootloader.
BOOTLOADER_BASE = 0x08000000      # the reset vector the core fetches after reset
FACTORY_APP_VECTOR_BASE = 0x08005000   # 07-series App vectors sit above the loader


def assert_requests_bootloader(rec, where=""):
    """Hold an ArmSim.watch_system_reset() record (after the image-specific drive
    ran) to the shared enter-bootloader contract."""
    assert rec.requested, (
        "%s: firmware did not request a system reset "
        "(no VECTKEY|SYSRESETREQ written to SCB->AIRCR)" % where)
    assert (rec.value >> 16) == 0x05FA and (rec.value & 0x4), (
        "%s: AIRCR write 0x%08x is not a VECTKEY|SYSRESETREQ reset request"
        % (where, rec.value or 0))


