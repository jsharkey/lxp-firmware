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
	$(HOSTCC) $(HOSTFLAGS) src/dsp/dsp_config.c src/modbus/modbus.c tests/test_dsp_config.c -o $(BUILD)/test_dsp_config
	@./$(BUILD)/test_dsp_config
	$(HOSTCC) $(HOSTFLAGS) src/variant.c tests/test_variant.c -o $(BUILD)/test_variant
	@./$(BUILD)/test_variant
	$(HOSTCC) $(HOSTFLAGS) src/can/bms_can.c tests/test_bms_can.c -o $(BUILD)/test_bms_can
	@./$(BUILD)/test_bms_can
	$(HOSTCC) $(HOSTFLAGS) src/sched/acfirst.c tests/test_acfirst.c -o $(BUILD)/test_acfirst
	@./$(BUILD)/test_acfirst

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
FACTORY_BIN ?= $(or $(LXP_FACTORY_BIN),reference/com_flat.bin)
HAVE_FACTORY := $(or $(strip $(LXP_FACTORY_HEX)),$(wildcard $(FACTORY_BIN)))

# The factory flat .bin: convert the vendor Intel .hex (gaps filled with 0xFF,
# every byte at its true flash address -- see hex2bin). Built only if missing;
# `make factory` is the friendly alias.
$(FACTORY_BIN):
	@test -n "$(LXP_FACTORY_HEX)" || { \
	  echo "$@: set LXP_FACTORY_HEX=/path/to/vendor.hex to build the factory image"; \
	  exit 1; }
	@mkdir -p $(dir $@)
	python3 tools/hex2bin.py "$(LXP_FACTORY_HEX)" "$@"

factory: $(FACTORY_BIN)

# The four test-file invocations (shared by the aggregate and the per-half
# convenience targets, so the command lines live in one place).
SIM_OURS_COMMON = python3 tests/test_arm_sim.py $(BUILD)/$(TARGET).bin
SIM_OURS_SELF   = python3 tests/test_arm_sim_self_only.py $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
SIM_OURS_HMI    = python3 tests/test_hmi_panel.py $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
SIM_FAC_COMMON  = python3 tests/test_arm_sim.py $(FACTORY_BIN)
SIM_FAC_ONLY    = python3 tests/test_arm_sim_factory_only.py $(FACTORY_BIN)
# Cross-image: settings persisted by one firmware are read by the other (needs both).
SIM_CROSS       = python3 tests/test_persist_crossimage.py $(BUILD)/$(TARGET).bin $(FACTORY_BIN)

# Every block runs even if an earlier one fails; the target fails only at the end
# if any did -- so a red test (e.g. the expected-red dongle/CAN scaffolding)
# never hides the blocks after it. Each file @-prints its own banner header,
# which stays the sole block delimiter (the recipes are @-silent).
test-sim-ours: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
	@rc=0; $(SIM_OURS_COMMON) || rc=1; $(SIM_OURS_SELF) || rc=1; $(SIM_OURS_HMI) || rc=1; exit $$rc

test-sim-factory: $(FACTORY_BIN)
	@rc=0; $(SIM_FAC_COMMON) || rc=1; $(SIM_FAC_ONLY) || rc=1; exit $$rc

# Interactive on-screen HMI: runs the firmware in the emulator and serves the
# LCD + 4 front-panel keys in a browser (tools/hmi_app.py). Override the port
# with PORT=... ; open http://localhost:$(PORT)/ . Needs `pip install unicorn`.
PORT ?= 8080
hmi: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).elf
	python3 tools/hmi_app.py --bin $(BUILD)/$(TARGET).bin --elf $(BUILD)/$(TARGET).elf --port $(PORT)

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
	$(SIM_OURS_HMI) || rc=1; \
	$(if $(HAVE_FACTORY),$(SIM_FAC_COMMON) || rc=1; $(SIM_FAC_ONLY) || rc=1; $(SIM_CROSS) || rc=1;,echo "# test-sim: no factory image (set LXP_FACTORY_HEX=... or 'make factory'); ran ours only";) \
	exit $$rc

# Focused time-window micro-tests (docs/35): a cheap complement to test-sim that
# drives ONLY the AC-First window-vs-RTC evaluator -- no boot, no Modbus. The SAME
# vectors run against our compiled acfirst.c (via ctypes) and the factory ARM
# evaluator called in isolation under Unicorn. The "ours" half needs only host
# `cc`; the factory half runs when an image + unicorn are present, else skips.
# Leaves `test` and `test-sim` unchanged -- this is an additional, narrow suite.
test-window: $(if $(HAVE_FACTORY),$(FACTORY_BIN))
	@mkdir -p $(BUILD)
	python3 tests/test_timewindow.py $(if $(HAVE_FACTORY),$(FACTORY_BIN),)

# Flashing helpers (uncomment the one matching your tooling). FLASH_ADDR follows
# the selected VARIANT: 0x08000000 for the 12000XP, 0x0800C800 for the 18kPV App
# (the 18kPV bootloader below that address is NOT part of this image).
# flash-stlink: $(BUILD)/$(TARGET).bin
#	st-flash write $< $(FLASH_ADDR)
# flash-openocd: $(BUILD)/$(TARGET).bin
#	openocd -f interface/stlink.cfg -f target/stm32f1x.cfg \
#	  -c "program $< $(FLASH_ADDR) verify reset exit"

.PHONY: all size clean test test-sim test-sim-ours test-sim-factory test-window factory hmi hmi-sim factory-hmi
