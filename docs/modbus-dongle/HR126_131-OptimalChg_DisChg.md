# HR 126-131 — OptimalChg_DisChg (48-slot time table)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

A **48-slot × 2-bit** table packed across 6 registers (8 slots per register, each
slot = bits in `0-2`): each half-hour of the day (`00:00-00:30`, …, `23:30-00:00`)
carries a mark **0 no action, 1 charging, 2 discharging**.

| reg | slots | time span |
|---|---|---|
| HR 126 | Time0-7 | 00:00-04:00 |
| HR 127 | Time8-15 | 04:00-08:00 |
| HR 128 | Time16-23 | 08:00-12:00 |
| HR 129 | Time24-31 | 12:00-16:00 |
| HR 130 | Time32-39 | 16:00-20:00 |
| HR 131 | Time40-47 | 20:00-00:00 |

## Side-effects of writing

**A configuration time-table, persisted to config flash and evaluated ARM-side**
against the clock. This is the classic register that makes the **"126 trap"**
concrete: **HR 126-131 is this config table**, while **IR 126 is an unrelated
status word** (generator energy / AC-First active bit) — different space, different
meaning ([`docs/25`](../25-modbus-register-spaces.md)). The ARM compares the
current half-hour slot against the RTC it owns; like the other time windows it is
not pushed to the DSP as a per-slot verdict.
