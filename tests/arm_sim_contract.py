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
