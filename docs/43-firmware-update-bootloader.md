# 43 — Firmware update: who enters the bootloader, and how

**Question.** The external Modbus dongle can drive firmware updates of the
inverter's chips (ARM com-MCU, DSP, …). Does that rely on the ARM cooperating —
entering a "flashing"/bootloader mode? **Yes, on both axes.** This doc records
the mechanism and the parity test built on it.

## The dongle doesn't flash anything itself

The dongle is a **transparent conduit** ([`docs/26`](26-dongle-firmware.md)): an
ESP32-C3 datalogger that relays opaque EG4-Modbus frames over RS-485, with the
**ARM as the Modbus slave**. It has no register map of its own and cannot write
flash on any chip. So every update path runs *through* the ARM, and the ARM has
to play along.

## DSP / peer chips: the ARM is the flashing *master*

For the control DSP (and the same family of peers), the ARM is the active
driver: it runs the `0x21/0x22/0x23` "EDSN" bootloader protocol over USART3
(session-start + sector erase → program-block → verify/commit), which the DSP's
sector-0 bootloader `FUN_00080aa8` services — **proven both ends** in
[`docs/05`](05-dsp-link.md). The dongle supplies the image bytes; nothing reaches
the DSP unless the ARM is alive and driving the loader. So a DSP update depends
**entirely** on ARM cooperation — the ARM *is* the thing that puts the DSP into
flashing mode.

## The ARM's own update: it reboots itself into its bootloader

The 07-series parts are a **bootloader + App** layout (bootloader at
`0x08000000`, App relocated to `0x08005000`; [`docs/11`](11-12000xp-revisions.md)).
To reflash the ARM App, something has to hand control back to that bootloader —
and the App does it to itself on command.

- **Trigger (proven, vendor spec).** Holding register **11 = `ResetSetting`**, a
  bitfield; **bit 7 = `InvReboot`**, documented as *"restart inverter"*
  (EG4 18kPV-12LV Modbus spec). The dongle relays an ordinary `0x06`/`0x10`
  write to reg 11 with that bit set. The other bits are sibling actions
  (`EnergyRecordClr`, `AllToDefault`, `FaultRecordClr`, BMS switch toggles, …);
  the full map is in [`include/inv/modbus_map.h`](../include/inv/modbus_map.h).
- **Mechanism (proven, static + executed).** The App contains the canonical
  inlined `NVIC_SystemReset` — `DSB; AIRCR = VECTKEY(0x05FA) | (PRIGROUP) |
  SYSRESETREQ; DSB; for(;;)` — writing **`0x05FA0004`** to **`SCB->AIRCR`
  (`0xE000ED0C`)**. Confirmed by executing the site at **`0x0802f378`** under the
  harness: it writes exactly that key (a second AIRCR site, `0x080361xx`, is a
  saturating-counter *watchdog* reset — a different path). On reset the core
  re-fetches SP/PC from `0x08000000`, i.e. the **bootloader**, which then stays
  in flash-loader mode instead of launching the App.

So: dongle → Modbus write `ResetSetting.InvReboot` → ARM `NVIC_SystemReset` →
bootloader at `0x08000000`. The ARM must cooperate (receive the command and reset
itself); the dongle cannot force it.

## What we can and cannot drive in the harness

The **command → reboot** path cannot be exercised as a pure black box in a cold
sim, for the same two reasons the relay behaviours can't ([`docs/19`](19-gpio-test-harness.md)):

- The factory's `ResetSetting` consumer runs from an **RTOS task**; and
- the factory's **dongle register writes are gated** — a reg-11 write injected on
  the USART3 harness is acknowledged but never lands in the central settings
  store `0x20009854` ([`docs/08`](08-arm-dsp-config-protocol.md)) where the
  consumer reads, so the reboot never fires. (Verified: 60M instructions after
  the write, no AIRCR access.)

What *is* solid: executing the factory's `NVIC_SystemReset` site writes the reset
key, and the architectural reset vector (`0x08000000`) sits **below** the App's
own vector table (`0x08005000`) — demonstrably the separate bootloader.

## The parity test (shared contract, per-image drive)

Following the established relay pattern ([`tests/arm_sim_contract.py`](../tests/arm_sim_contract.py)):
both images are held to one contract — *the reboot path writes
`VECTKEY|SYSRESETREQ` to `SCB->AIRCR`, requesting the reset into the bootloader* —
and each is driven through its own path:

- **Factory** ([`test_arm_sim_factory_only.py`](../tests/test_arm_sim_factory_only.py)):
  execute the `NVIC_SystemReset` site `0x0802f378` by address; assert the reset
  request + that `0x08000000` is below the App vectors. The wiring to the
  `InvReboot` command rests on the spec + static RE above, not an end-to-end cold
  drive (documented, not claimed otherwise).
- **Ours** ([`test_arm_sim_self_only.py`](../tests/test_arm_sim_self_only.py)):
  **black box** — feed the real `ResetSetting.InvReboot` Modbus write over the
  UART; our firmware now acts on it (the HR 11 `ResetSetting` bit-7 handler
  `cmd_reboot()` in [`src/main.c`](../src/main.c) writes `VECTKEY|SYSRESETREQ`
  to `SCB->AIRCR` directly, as the factory does) and requests the reset. The
  monolithic 12000XP build keeps its vectors at
  `0x08000000`, so the boot PC the core fetches is present and in flash.

The harness capability is `ArmSim.watch_system_reset()` ([`tools/arm_sim.py`](../tools/arm_sim.py)):
it flags the `AIRCR` reset-key write and halts there, so the post-reset spin
never runs and the test inspects the reset target instead.

## Status / next steps

- [x] ARM self-reboot mechanism + trigger identified; parity test green on both
      images (factory by its reset site, ours black-box by the real command).
- [ ] Drive the factory's `InvReboot` **command path** end-to-end — blocked on
      the same RTOS task-scheduling / dongle-store-routing work [`docs/19`](19-gpio-test-harness.md)
      leaves open. When that lands, the factory half can move to the common
      black-box file.
- [ ] Reimplement the DSP-side `0x21/0x22/0x23` *master* flashing driver in our
      firmware (we currently push config, not firmware) and add its parity test.
