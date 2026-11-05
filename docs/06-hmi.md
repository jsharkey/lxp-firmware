# HMI (LCD + keypad menu system)

Status: **architecture reverse-engineered; a faithful data-driven module built
with host-tested navigation.** Full menu population + the LCD/keypad pin map are
the remaining work (the latter needs the schematic).

## How the stock HMI works (RE)

The settings menu is **data-driven**, not hand-coded per screen. `sub_08005938`
(named `fn_` candidates aside, this is the main menu builder) fills a menu table
in RAM at `0x20000934`:

- Each menu item is a **fixed 0x1C-byte struct** (consecutive label stores are
  `0x1C` apart), with the **`char*` label at offset +8**:
  ```
  str "SN: "  -> [tbl+0x08]
  str "FW: "  -> [tbl+0x24]   (+0x1C)
  str "Model: " -> [tbl+0x40] (+0x1C)
  ...
  ```
- Items are grouped into pages (blocks at `tbl+0xB0`, `+0x13C`, `+0x1C8`, …).
- The labels are the ordered catalog in `reference/string_catalog.txt` /
  `include/inv/hmi_menu.h` (96-item settings menu, in order).
- Navigation/handlers: a dispatcher (`sub_0800d1e4`) routes a selected item to a
  screen handler; sub-screens like `fn_Hybrid_Setting` / `fn_AC_Couple` call
  shared helpers `sub_0800f1b8` (draw screen) and `sub_080104ec` (edit value).
- Keys are the 4-button pad ESC/UP/DOWN/ENTER (per "KEY Ageing Test").

So the shape is: **menu table + navigation state machine + value-edit helper**,
with items bound to settings (holding registers).

## The reimplementation

Same shape, cleaned up and hardware-abstracted:

| File | Role |
|---|---|
| `include/inv/hmi.h` | item/menu types, navigation API, LCD+keypad port interface |
| `src/hmi/hmi.c` | navigation engine: move / enter-submenu / edit-value / action / back; scroll; clamp; commit vs cancel |
| `src/hmi/hmi_model.c` | the menu tree (data), bound to `HR_*`/`IR_*` registers with ranges from the protocol doc |
| `src/hmi/hmi_port.c` | LCD + keypad port — 20×4 HD44780 over a PCF8574 I²C backpack (bit-banged), debounced keys on PA8/PA11/PC8/PC9 (`docs/27`) |
| `include/inv/hmi_panel.h` | panel wiring shared by the firmware + the emulator model |
| `tests/test_hmi.c` | host tests (`make test`, 14 checks) |
| `tests/test_hmi_panel.py` | end-to-end on the emulator: keys → LCD text + register writes (`make test-sim-ours`) |

Item kinds: `HMI_INFO` (read-only reg display), `HMI_U16` (ranged numeric edit),
`HMI_ENUM` (choice list), `HMI_SUBMENU`, `HMI_ACTION`. Editable items read+write
**the same holding-register store the Modbus slave uses**, so an HMI edit and a
Modbus write are consistent.

Values format with scale + unit (e.g. `IR_VBAT` raw 525 → `52.5V`); enums show
their choice label. Navigation is fully unit-tested on the host (move, scroll,
enter/commit/cancel edit, min/max clamp, submenu push/pop, action callback).

## TODO

- [ ] Populate the full 96-item menu + submenus from `string_catalog.txt` +
      `modbus_map.h` (the model is currently a representative subset).
- [ ] Item types/choices that need RE (enum option lists, per-item scale) —
      confirm against the stock menu-builder tables.
- [x] `hmi_port.c`: LCD driver + debounced keypad scan — done for a **20×4
      HD44780 over a PCF8574 I²C backpack** (bit-banged), keys on the factory
      key pins PA8/PA11/PC8/PC9. Runs end-to-end in the emulator with an
      on-screen app (`make hmi`, `docs/27`). The *factory* SPI1 panel protocol
      is still undecoded (`docs/16`); byte-matching it is a non-goal, so this
      clean, observable panel stands in until the schematic pins the real one.
- [ ] Settings persistence (EEPROM/flash) on commit; range validation shared
      with the Modbus write path.
- [ ] Multi-byte/string items (SN, FW, time) rendering.
