# HR 12-14 — real-time clock

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | low byte | high byte |
|---|---|---|
| HR 12 | Year (17-255) | Month (1-12) |
| HR 13 | Date (1-31) | Hour (0-23) |
| HR 14 | Minute (0-59) | Second (0-59) |

## Side-effects of writing

**The ARM owns the clock and streams it to the DSP.** The DSP has no power-off
RTC, so the ARM re-provisions it each boot and pushes the time on the USART3 link
as a dedicated frame (`0xA5 0xA5` preamble + y/m/d h:m:s, builder `sub_08021df8`)
— see [`docs/08`](../08-arm-dsp-config-protocol.md)/[`docs/09`](../09-dsp-persistence-and-clock.md)
and [`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md).

The clock is also the reference the ARM uses to **evaluate the time-window
settings** (AC-charge/charge-priority/forced-discharge
[`holding-064_089-...`](holding-064_089-charge-discharge-schedule.md), AC-First
[`holding-152_157-...`](holding-152_157-ACFirst-windows.md), OptimalChg
[`holding-126_131-...`](holding-126_131-OptimalChg_DisChg.md)). Writable with `0x10`
(one of only two such blocks, with the SN).
