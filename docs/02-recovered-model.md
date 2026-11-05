# Recovered data model (from strings)

This captures the device's observable *data model* — modes, faults, settings,
telemetry — recovered from the string table of the original "com" firmware.
It is the clean-room specification the C reimplementation targets. Verbatim
strings are the ground truth; everything about numeric encoding is TODO.

## Telemetry / live values (string labels)

- Grid frequency `Fgrid:`, EPS frequency `Feps:`
- Grid voltage per leg `VgridL1N:`, `VgridL2N:` → **split-phase (L1/L2/N)**
- Energy counters: `Eeps_day:`, `Eeps_all:`, `EepsL1N_day/all:`, `EepsL2N_day/all:`
- Grid import: `Grid Today Import:`, `Grid Total Import:`
- `Grid_OnOff_Cnt:` (grid connect/disconnect counter)
- Battery `SOC`, `Bat SOC`

## Operating states — AUTHORITATIVE
See `include/inv/states.h`. Input register 0, a **bitmask** (Table 9 of the
Modbus spec): PV-on-grid `0x04`, PV-charge `0x08`, Bat-on-grid `0x10`,
AC-charge `0x20`, Bat-off-grid `0x40`, PV-off-grid `0x80`; combinations OR.

## Faults & Warnings — AUTHORITATIVE
See `include/inv/faults.h`. Two 32-bit bitfields (Table 10): `FaultCode`
(regs 60/61, codes E000-E031) and `WarningCode` (regs 62/63, W000-W031). The
raw HMI strings map onto these bits (several "fault-looking" strings are
actually warnings, e.g. BatVoltHigh = W025).

## External comms — AUTHORITATIVE
See `include/inv/modbus_map.h`. The full Modbus-RTU slave interface (RS-485,
19200 8N1; input regs 0-152, holding regs 0-198) is specified by the public
EG4 18kPV-12LV protocol document. This is a large, directly-implementable slice
of the firmware.

## Settings / menu tree
See `include/inv/settings.h`. Major groups: Battery, Charge/Discharge,
AC-Charge, AC-Couple, Generator-Charge, Grid/Metering, EPS/Output, Identity,
plus service menus (LCD/KEY ageing tests, Update).

## What is NOT yet recovered (and how to get it)

| Unknown | Why it matters | How to recover |
|---|---|---|
| ~~Numeric value of each fault/state enum~~ | ✅ **DONE** — from Modbus Tables 9 & 10 | — |
| ~~Modbus/RS485 register map~~ | ✅ **DONE** — `modbus_map.h` | — |
| Settings storage layout (flash/EEPROM) | load/save compatibility | locate the save/load routine; dump a real device's config page |
| HMI **menu tree** (pointer tables) | reproduce the UI | pointer-table resolver (see `docs/03`); the schematic confirms LCD/key pins |
| **ARM↔DSP internal protocol** (framing, IDs, scaling) | the remaining hard interface | protocol spec from you, or a UART/CAN bus capture on a live unit |
| Exact MCU part / flash+RAM size | linker script & HAL | from the schematic you're providing |
| Font/bitmap table format | HMI rendering | decode the glyph tables (the ~28% non-code flash region) |

The **ARM↔DSP internal protocol** is now the critical unknown: the external
Modbus side is fully specified, but the link that actually drives the DSP must
still be reproduced exactly. (Note: the ARM likely *bridges* much of the Modbus
data to/from the DSP, so the two protocols are probably closely related — a good
lead for the bus capture.)
