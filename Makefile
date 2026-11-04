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
	$(HOSTCC) $(HOSTFLAGS) src/modbus/modbus.c tests/test_modbus.c -o $(BUILD)/test_modbus
	@./$(BUILD)/test_modbus
	$(HOSTCC) $(HOSTFLAGS) src/hmi/hmi.c src/hmi/hmi_model.c tests/test_hmi.c -o $(BUILD)/test_hmi
	@./$(BUILD)/test_hmi
	$(HOSTCC) $(HOSTFLAGS) src/dsp/dsp_config.c src/modbus/modbus.c tests/test_dsp_config.c -o $(BUILD)/test_dsp_config
	@./$(BUILD)/test_dsp_config
	$(HOSTCC) $(HOSTFLAGS) src/variant.c tests/test_variant.c -o $(BUILD)/test_variant
	@./$(BUILD)/test_variant

# GPIO-behaviour tests on the Unicorn harness (tools/arm_sim.py). Needs: pip
# install unicorn.
#
# The common tests (tests/test_arm_sim.py) are run twice -- the SAME test code
# against each firmware image, passed as a command-line argument: once against
# our build, and (when a factory image is provided) once against the factory
# oracle. Target-specific tests that must name internal symbols/addresses live in
# their own files: test_arm_sim_self_only.py (our firmware) and
# test_arm_sim_factory_only.py (the factory image).
#
# The factory image is never committed (it is proprietary); give one via
# $LXP_FACTORY_HEX (a vendor .hex, converted in-memory), $LXP_FACTORY_BIN, or
# reference/com_flat.bin. Without one, the factory runs are skipped and the
# target is still green on our firmware alone.
FACTORY_IMG := $(or $(LXP_FACTORY_HEX),$(LXP_FACTORY_BIN),$(wildcard reference/com_flat.bin))
test-sim: $(BUILD)/$(TARGET).bin
	python3 tests/test_arm_sim.py $(BUILD)/$(TARGET).bin
	python3 tests/test_arm_sim_self_only.py
ifneq ($(FACTORY_IMG),)
	python3 tests/test_arm_sim.py $(FACTORY_IMG)
	LXP_FACTORY_IMG=$(FACTORY_IMG) python3 tests/test_arm_sim_factory_only.py
else
	@echo "# (no factory image: set LXP_FACTORY_HEX/LXP_FACTORY_BIN to run the factory oracle)"
endif

# Flashing helpers (uncomment the one matching your tooling). FLASH_ADDR follows
# the selected VARIANT: 0x08000000 for the 12000XP, 0x0800C800 for the 18kPV App
# (the 18kPV bootloader below that address is NOT part of this image).
# flash-stlink: $(BUILD)/$(TARGET).bin
#	st-flash write $< $(FLASH_ADDR)
# flash-openocd: $(BUILD)/$(TARGET).bin
#	openocd -f interface/stlink.cfg -f target/stm32f1x.cfg \
#	  -c "program $< $(FLASH_ADDR) verify reset exit"

.PHONY: all size clean test test-sim
