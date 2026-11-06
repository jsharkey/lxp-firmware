# Clock frame — ARM → DSP real-time clock stream

> **ARM→DSP**, a *third* framing on this wire (not a type-1 block, not the
> bootloader). Unsolicited, streamed continuously. See the [index](README.md).

The Control DSP has **no power-off-surviving RTC** (docs/09), so the ARM — which
owns the clock — streams it to the DSP:

```
preamble : 0xA5 0xA5
payload  : year, month, day, hour, minute, second   (the ARM's RTC)
```

- Source buffer: ARM RAM `0x20009754`; builder `sub_08021df8`.
- Sent **unsolicited** (unlike the config blocks, which are a continuous full
  snapshot the DSP diffs). This is the one frame on the link that is genuinely
  push-only with no request.
- Lets the DSP evaluate any time-of-day logic it needs against a clock it can't
  keep itself. (The **AC-First window start/stop times are evaluated on the ARM**
  against this same RTC, not shipped to the DSP as clock-compares — see
  [`block-00`](block-00-output-priority.md) and docs/07.)

Background: [`docs/09`](../09-dsp-persistence-and-clock.md) (DSP has no NV storage /
no RTC; ARM owns both), [`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md).
