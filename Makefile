# Build the open EG4 12000XP com-MCU firmware -> build/firmware.{elf,bin,hex}
# Requires: arm-none-eabi-gcc (gcc-arm-none-eabi)

TARGET   := firmware
BUILD    := build

# --- Product variant -------------------------------------------------------
# Select the target model.  Both descriptors are always linked in (see
# src/variant.c); this picks the one the build is specialised for and the
# matching flash/partition layout.
#
#   make                 # EG4 12000XP (monolithic image, vectors @0x08000000)
#   make VARIANT=18kpv   # EG4 18kPV   (App over bootloader, vectors @0x0800C800)
#   make VARIANT=6000xp  # EG4 6000XP  (App over bootloader, vectors @0x08005000)
#
VARIANT ?= 12000xp
ifeq ($(VARIANT),18kpv)
  LDSCRIPT    := ldscripts/stm32f103_18kpv_app.ld
  VARIANT_DEF := -DINV_VARIANT_18KPV
  FLASH_ADDR  := 0x0800C800
else ifeq ($(VARIANT),6000xp)
  LDSCRIPT    := ldscripts/stm32f103_6kxp_app.ld
  VARIANT_DEF := -DINV_VARIANT_6000XP
  FLASH_ADDR  := 0x08005000
else ifeq ($(VARIANT),12000xp)
  LDSCRIPT    := ldscripts/stm32f103ve.ld
  VARIANT_DEF :=
  FLASH_ADDR  := 0x08000000
else
  $(error Unknown VARIANT '$(VARIANT)' (use 12000xp, 18kpv or 6000xp))
endif

CROSS    := arm-none-eabi-
CC       := $(CROSS)gcc
OBJCOPY  := $(CROSS)objcopy
SIZE     := $(CROSS)size

SRCS := $(shell find src -name '*.c')
OBJS := $(patsubst src/%.c,$(BUILD)/%.o,$(SRCS))

CPU     := -mcpu=cortex-m3 -mthumb
CFLAGS  := $(CPU) -std=c11 -Og -g3 -ffunction-sections -fdata-sections \
           -Wall -Wextra -Iinclude $(VARIANT_DEF)
LDFLAGS := $(CPU) -T$(LDSCRIPT) -nostartfiles -Wl,--gc-sections \
           -Wl,-Map=$(BUILD)/$(TARGET).map --specs=nano.specs --specs=nosys.specs

all: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex size

$(BUILD)/%.o: src/%.c | $(BUILD)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(OBJS) $(LDFLAGS) -o $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

size: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)

# Host-side unit tests (no hardware). Uses the system gcc, not the cross tool.
HOSTCC ?= cc
HOSTFLAGS := -std=c11 -Wall -Wextra -Iinclude
test:
	@mkdir -p $(BUILD)
	$(HOSTCC) $(HOSTFLAGS) tests/test_ringbuf.c -o $(BUILD)/test_ringbuf
	@./$(BUILD)/test_ringbuf
	$(HOSTCC) $(HOSTFLAGS) src/modbus/modbus.c tests/test_modbus.c -o $(BUILD)/test_modbus
	@./$(BUILD)/test_modbus
	$(HOSTCC) $(HOSTFLAGS) src/hmi/hmi.c src/hmi/hmi_model.c tests/test_hmi.c -o $(BUILD)/test_hmi
	@./$(BUILD)/test_hmi
	$(HOSTCC) $(HOSTFLAGS) src/dsp/dsp_config.c src/dsp/dsp_slots.c src/modbus/modbus.c tests/test_dsp_config.c -o $(BUILD)/test_dsp_config
	@./$(BUILD)/test_dsp_config
	$(HOSTCC) $(HOSTFLAGS) src/variant.c tests/test_variant.c -o $(BUILD)/test_variant
	@./$(BUILD)/test_variant
	$(HOSTCC) $(HOSTFLAGS) src/can/bms_can.c tests/test_bms_can.c -o $(BUILD)/test_bms_can
	@./$(BUILD)/test_bms_can
	$(HOSTCC) $(HOSTFLAGS) src/bms/bms_limits.c tests/test_bms_limits.c -o $(BUILD)/test_bms_limits
	@./$(BUILD)/test_bms_limits
	$(HOSTCC) $(HOSTFLAGS) src/sched/acfirst.c tests/test_acfirst.c -o $(BUILD)/test_acfirst
	@./$(BUILD)/test_acfirst
	$(HOSTCC) $(HOSTFLAGS) src/sched/optchg.c tests/test_optchg.c -o $(BUILD)/test_optchg
	@./$(BUILD)/test_optchg
	$(HOSTCC) $(HOSTFLAGS) src/rtc/rtc.c tests/test_rtc.c -o $(BUILD)/test_rtc
	@./$(BUILD)/test_rtc
	$(HOSTCC) $(HOSTFLAGS) src/state/classify.c tests/test_classify.c -o $(BUILD)/test_classify
	@./$(BUILD)/test_classify
	$(HOSTCC) $(HOSTFLAGS) src/state/command.c tests/test_command.c -o $(BUILD)/test_command
	@./$(BUILD)/test_command
	$(HOSTCC) $(HOSTFLAGS) src/safety/safety_cpu.c src/variant.c tests/test_w008.c -o $(BUILD)/test_w008
	@./$(BUILD)/test_w008
	$(HOSTCC) $(HOSTFLAGS) src/energy/energy.c tests/test_energy.c -o $(BUILD)/test_energy
	@./$(BUILD)/test_energy
	$(HOSTCC) $(HOSTFLAGS) src/settings/settings_validate.c tests/test_settings_validate.c -o $(BUILD)/test_settings_validate
	@./$(BUILD)/test_settings_validate
	$(HOSTCC) $(HOSTFLAGS) src/telemetry/telemetry.c tests/test_telemetry.c -o $(BUILD)/test_telemetry
	@./$(BUILD)/test_telemetry
	$(HOSTCC) $(HOSTFLAGS) src/dsp/dsp_rx.c tests/test_dsp_rx.c -o $(BUILD)/test_dsp_rx
	@./$(BUILD)/test_dsp_rx
	$(HOSTCC) $(HOSTFLAGS) src/safety/safety_rx.c src/modbus/modbus.c tests/test_safety_rx.c -o $(BUILD)/test_safety_rx
	@./$(BUILD)/test_safety_rx
	$(HOSTCC) $(HOSTFLAGS) src/sched/dischg_gate.c tests/test_dischg_gate.c -o $(BUILD)/test_dischg_gate
	@./$(BUILD)/test_dischg_gate
	@python3 tools/reg_coverage.py --check   # T22: a covering test must be recorded in its register's doc

# Register-coverage bookkeeping (T22): cross-reference the register map, the
# tests, and each register's `## Test coverage` doc section. Read-only.
coverage-report:
	@python3 tools/reg_coverage.py

coverage-check:
	@python3 tools/reg_coverage.py --check

# GPIO-behaviour tests on the Unicorn harness (tools/arm_sim.py). Needs: pip
# install unicorn.
#
# The common tests (tests/test_arm_sim.py) run the SAME test code against each
# firmware image, given as a flat .bin on the command line (it rejects a .hex).
# Target-specific tests that must name internal symbols/addresses live in their
# own files: test_arm_sim_self_only.py (our firmware) and
# test_arm_sim_factory_only.py (the factory image).
#
#   make test-sim          # test-sim-ours + test-sim-factory
#   make test-sim-ours     # build our fw; common + self-only tests on it
#   make factory           # convert $LXP_FACTORY_HEX -> $(FACTORY_BIN)
#   make test-sim-factory  # common + factory-only tests on the factory .bin
#
# The factory image is never committed (it is proprietary). The `factory` target
# converts a vendor .hex into the flat .bin the tests load. `make test-sim` runs
# the factory half only when an image is available (a .hex to convert, or an
# already-built .bin), so it stays green on our firmware alone; point it at a
# prebuilt .bin with FACTORY_BIN=/path (LXP_FACTORY_BIN is honoured too).
# Canonical reference image: the 07-series 12000XP (ceaa-07xx_vE_260214). Drop the
# vendor .hex under reference/ -- the flat .bin is NAMED AFTER IT (so the filename
# says which image, instead of a generic com_flat.bin). Override the hex with
# LXP_FACTORY_HEX, or point straight at a prebuilt .bin with LXP_FACTORY_BIN.
FACTORY_HEX ?= $(or $(LXP_FACTORY_HEX),$(firstword $(wildcard reference/*ceaa-07xx*.hex)))
FACTORY_BIN ?= $(or $(LXP_FACTORY_BIN),$(if $(FACTORY_HEX),reference/$(basename $(notdir $(FACTORY_HEX))).bin,reference/ceaa-07xx_vE_260214.bin))
HAVE_FACTORY := $(or $(strip $(FACTORY_HEX)),$(wildcard $(FACTORY_BIN)))

# The factory flat .bin: convert the vendor Intel .hex (gaps filled with 0xFF,
# every byte at its true flash address -- see hex2bin). Built only if missing;
# `make factory` is the friendly alias. The .bin is named after the .hex.
$(FACTORY_BIN):
	@test -n "$(FACTORY_HEX)" || { \
	  echo "$@: drop the 07-series vendor .hex under reference/ (or set LXP_FACTORY_HEX=/path)"; \
	  exit 1; }
	@mkdir -p $(dir $@)
	python3 tools/hex2bin.py "$(FACTORY_HEX)" "$@"

factory: $(FACTORY_BIN)

# The four test-file invocations (shared by the aggregate and the per-half
# convenience targets, so the command lines live in one place).
SIM_OURS_COMMON = python3 tests/test_arm_sim.py $(BUILD)/$(TARGET).bin
SIM_OURS_SELF   = python3 tests/test_arm_sim_self_only.py $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
SIM_FAC_COMMON  = LXP_MODBUS_PORT=dsp python3 tests/test_arm_sim.py $(FACTORY_BIN)
SIM_FAC_ONLY    = python3 tests/test_arm_sim_factory_only.py $(FACTORY_BIN)
# Cross-image: settings persisted by one firmware are read by the other (needs both).
SIM_CROSS       = python3 tests/test_persist_crossimage.py $(BUILD)/$(TARGET).bin $(FACTORY_BIN)
# ARM->DSP config-push live capture: writes a holding reg over the dongle, then
# captures which config-frame byte moves. Same spec for ours + factory (the
# factory half self-skips when no image is present).
SIM_PUSH        = python3 tests/test_dsp_push.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf
# Accumulated energy counters (IR 28-37 / 40-59): factory accumulator vs ours.
SIM_ENERGY      = python3 tests/test_energy.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf
# Holding-register write semantics: out-of-range -> exception, read-only, etc.
SIM_WRSEM       = python3 tests/test_settings_validate.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf
# ARM-computed telemetry registers: powers /10, Seps 1:1, RunningTime split.
SIM_TELEM       = python3 tests/test_telemetry.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf
# USART3 RX demux: Modbus (03/04/06/10) + DSP bootloader (21/22/23); 0x49 rejected.
SIM_DSPRX       = python3 tests/test_dsp_rx.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf
# Discharge-by-voltage hysteresis gate: factory oracle (sub_0801ed28) vs the T15
# spec; ours' pure reimplementation is covered by the host test test_dischg_gate.c.
SIM_DGATE       = python3 tests/test_dischg_gate.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),)
# inverter->battery CAN keep-alive TX capture (T11b): 0x305 DLC8 all-zero, both images.
SIM_CANTX       = python3 tests/test_can_tx.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),) --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf

# Every block runs even if an earlier one fails; the target fails only at the end
# if any did -- so a red test (e.g. the expected-red dongle/CAN scaffolding)
# never hides the blocks after it. Each file @-prints its own banner header,
# which stays the sole block delimiter (the recipes are @-silent).
test-sim-ours: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
	@rc=0; $(SIM_OURS_COMMON) || rc=1; $(SIM_OURS_SELF) || rc=1; $(SIM_PUSH) || rc=1; $(SIM_ENERGY) || rc=1; $(SIM_WRSEM) || rc=1; $(SIM_TELEM) || rc=1; $(SIM_DSPRX) || rc=1; $(SIM_CANTX) || rc=1; $(SIM_DGATE) || rc=1; exit $$rc

test-sim-factory: $(FACTORY_BIN)
	@rc=0; $(SIM_FAC_COMMON) || rc=1; $(SIM_FAC_ONLY) || rc=1; exit $$rc

# The interactive graphic-HMI simulator on screen (tools/factory_hmi_app.py,
# docs/28): renders whatever firmware's real LCD output and feeds the four keys.
# It is firmware-agnostic — defaults to the open-source build; pass FIRMWARE=path
# to run a vendor .hex/.bin instead. Open http://localhost:$(HMI_PORT)/ .
HMI_PORT ?= 8090
FIRMWARE ?=
hmi-sim: $(if $(FIRMWARE),,$(BUILD)/$(TARGET).bin)
	python3 tools/factory_hmi_app.py $(FIRMWARE) --port $(HMI_PORT)

# Convenience: the factory image specifically.
factory-hmi: $(FACTORY_BIN)
	python3 tools/factory_hmi_app.py $(FACTORY_BIN) --port $(HMI_PORT)

# Aggregate: build/convert whatever's needed up front (the factory .bin only when
# an image is available), run all blocks, then fail if any did. Green on our
# firmware alone when there is no factory image.
test-sim: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf $(if $(HAVE_FACTORY),$(FACTORY_BIN))
	@rc=0; \
	$(SIM_OURS_COMMON) || rc=1; \
	$(SIM_OURS_SELF) || rc=1; \
	$(SIM_PUSH) || rc=1; \
	$(SIM_ENERGY) || rc=1; \
	$(SIM_WRSEM) || rc=1; \
	$(SIM_TELEM) || rc=1; \
	$(SIM_DSPRX) || rc=1; \
	$(SIM_CANTX) || rc=1; \
	$(SIM_DGATE) || rc=1; \
	$(if $(HAVE_FACTORY),$(SIM_FAC_COMMON) || rc=1; $(SIM_FAC_ONLY) || rc=1; $(SIM_CROSS) || rc=1;,echo "# test-sim: no factory image (set LXP_FACTORY_HEX=... or 'make factory'); ran ours only";) \
	exit $$rc

# Focused time-window micro-tests (docs/35): a cheap complement to test-sim that
# drives ONLY the window-vs-RTC evaluators -- no boot, no Modbus. The SAME vectors
# run against our firmware and the factory image, BOTH under Unicorn: our
# acfirst_window_active() is resolved by symbol from the ELF and called in
# isolation, and the factory evaluators (AC-First / AC-charge) are called the same
# way. Needs `pip install unicorn`; the factory half also needs an image, else it
# skips. Leaves `test` and `test-sim` unchanged -- this is an additional suite.
# (Host-only, toolchain-free coverage of the pure function is in test_acfirst.c.)
test-window: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf $(if $(HAVE_FACTORY),$(FACTORY_BIN))
	python3 tests/test_timewindow.py --ours-bin $(BUILD)/$(TARGET).bin --ours-elf $(BUILD)/$(TARGET).elf $(if $(HAVE_FACTORY),$(FACTORY_BIN),)

# Flashing helpers (uncomment the one matching your tooling). FLASH_ADDR follows
# the selected VARIANT: 0x08000000 for the 12000XP, 0x0800C800 for the 18kPV App
# (the 18kPV bootloader below that address is NOT part of this image).
# flash-stlink: $(BUILD)/$(TARGET).bin
#	st-flash write $< $(FLASH_ADDR)
# flash-openocd: $(BUILD)/$(TARGET).bin
#	openocd -f interface/stlink.cfg -f target/stm32f1x.cfg \
#	  -c "program $< $(FLASH_ADDR) verify reset exit"

.PHONY: all size clean test test-sim test-sim-ours test-sim-factory test-window coverage-report coverage-check factory hmi-sim factory-hmi
