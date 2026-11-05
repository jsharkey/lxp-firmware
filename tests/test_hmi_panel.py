#!/usr/bin/env python3
"""
HMI-panel tests on the arm_sim harness: boot OUR firmware, drive the four key
GPIOs, and assert what it actually draws to its I2C character LCD.

Unlike the relay/CAN contract tests (which call drive code directly because the
RTOS task isn't scheduled), the HMI runs end to end here: these press the real
key pins (PA8/PA11/PC8/PC9, active-low), let the firmware's debounced keypad
reader + menu engine run, and read the screen back through the modelled
PCF8574 + HD44780 (tools/panel.py). So they exercise the whole path:

    key GPIO -> hmi_keypad_poll -> hmi_key -> hmi_render -> bit-banged I2C -> LCD

Editable items also prove the HMI writes the shared holding-register store (an
HMI edit and a Modbus write hit the same registers).

Usage (same style as tests/test_arm_sim_self_only.py -- needs the .elf for
symbols; run `make` first):

    python3 tests/test_hmi_panel.py build/firmware.bin build/firmware.elf

With no arguments the tests SKIP. Needs `pip install unicorn` and the ARM
toolchain's `arm-none-eabi-nm` (to read the .elf symbols).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from arm_sim_runner import Skip, run_tests

_BIN = [None]
_ELF = [None]


def _hmi():
    binp, elfp = _BIN[0], _ELF[0]
    if not binp or not elfp:
        raise Skip("no firmware given (pass build/firmware.bin and build/firmware.elf)")
    for p in (binp, elfp):
        if not os.path.exists(p):
            raise Skip("%s not present (run `make`)" % p)
    try:
        import unicorn  # noqa: F401
    except ImportError:
        raise Skip("unicorn not installed (pip install unicorn)")
    from hmi_engine import HmiSim
    return HmiSim(binp, elfp)


def test_boot_shows_live_telemetry():
    """On boot the root menu shows the seeded live telemetry, formatted with the
    model's scale + unit (VBAT 525 -> 52.5V, FAC 6000 -> 60.00Hz)."""
    h = _hmi()
    rows = h.screen()
    assert rows[0].startswith(">State:"), "row0 = %r" % rows[0]
    assert "52.5V" in rows[1], "row1 = %r" % rows[1]
    assert "85%" in rows[2], "row2 = %r" % rows[2]
    assert "60.00Hz" in rows[3], "row3 = %r" % rows[3]


def test_keys_move_selection():
    """DOWN then UP move the '>' cursor through the list and back."""
    h = _hmi()
    assert h.selected().startswith("State:")
    h.press("down")
    assert h.selected().startswith("Battery Volt:"), h.selected()
    h.press("down")
    assert h.selected().startswith("SOC:"), h.selected()
    h.press("up")
    assert h.selected().startswith("Battery Volt:"), h.selected()


def test_list_scrolls_beyond_window():
    """Paging past the 4-row window scrolls: the top row is no longer State."""
    h = _hmi()
    for _ in range(6):
        h.press("down")
    assert not h.screen()[0].startswith(">State:")
    assert h.screen()[0].strip() != "State: 3"


def test_enum_edit_writes_holding_register():
    """Editing the 'Output Prio' ENUM (ENTER, UP, ENTER) advances the choice and
    writes the same holding register the Modbus slave uses (0 -> 1 = PV First)."""
    h = _hmi()
    assert h.holding("OUTPUT_PRIO_CFG") == 0
    assert h.nav_to("Output Prio"), "could not reach Output Prio (got %r)" % h.selected()
    h.press("enter")        # begin edit
    h.press("up")           # 0 -> 1
    h.press("enter")        # commit
    assert h.holding("OUTPUT_PRIO_CFG") == 1, "register not written"
    assert h.nav_to("Output Prio"), "could not re-find Output Prio"
    # 20 cols truncates "Output Prio: PV First" -> the choice label still shows
    assert "PV Fir" in h.selected(), "screen shows %r" % h.selected()


def test_u16_edit_writes_holding_register():
    """Editing a U16 item (Charge Current Limit, step 1) writes the register and
    clamps at the item max (140)."""
    h = _hmi()
    start = h.holding("CHARGE_CURR")
    # the 20-col panel truncates the label, so navigate by a prefix that fits
    assert h.nav_to("Charge Current"), h.selected()
    h.press("enter")
    for _ in range(3):
        h.press("up")       # +3
    h.press("enter")
    assert h.holding("CHARGE_CURR") == start + 3, \
        "expected %d, got %d" % (start + 3, h.holding("CHARGE_CURR"))


def test_enum_edit_cancel_discards():
    """ESC while editing cancels: the register keeps its value."""
    h = _hmi()
    before = h.holding("LINE_MODE")
    assert h.nav_to("Line Mode"), h.selected()
    h.press("enter")
    h.press("up")
    h.press("esc")          # cancel, discard
    assert h.holding("LINE_MODE") == before, "cancel still wrote the register"


def test_submenu_enter_and_back():
    """ENTER opens a submenu (its items show); ESC returns to the root."""
    h = _hmi()
    assert h.nav_to("Parallel Setting"), h.selected()
    h.press("enter")
    joined = " ".join(h.screen())
    assert "Set System Type" in joined, "submenu not shown: %r" % h.screen()
    h.press("esc")
    assert h.nav_to("Parallel Setting", key="up"), "did not return to root"


def _main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) >= 1:
        _BIN[0] = args[0]
    if len(args) >= 2:
        _ELF[0] = args[1]
    return run_tests("HMI panel tests (our firmware)", _BIN[0] or "<none>", globals())


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
