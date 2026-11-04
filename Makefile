# Build the open EG4 12000XP com-MCU firmware -> build/firmware.{elf,bin,hex}
# Requires: arm-none-eabi-gcc (gcc-arm-none-eabi)

TARGET   := firmware
BUILD    := build
LDSCRIPT := ldscripts/stm32f103ve.ld

CROSS    := arm-none-eabi-
CC       := $(CROSS)gcc
OBJCOPY  := $(CROSS)objcopy
SIZE     := $(CROSS)size

SRCS := $(shell find src -name '*.c')
OBJS := $(patsubst src/%.c,$(BUILD)/%.o,$(SRCS))

CPU     := -mcpu=cortex-m3 -mthumb
CFLAGS  := $(CPU) -std=c11 -Og -g3 -ffunction-sections -fdata-sections \
           -Wall -Wextra -Iinclude
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

# Flashing helpers (uncomment the one matching your tooling):
# flash-stlink: $(BUILD)/$(TARGET).bin
#	st-flash write $< 0x08000000
# flash-openocd: $(BUILD)/$(TARGET).bin
#	openocd -f interface/stlink.cfg -f target/stm32f1x.cfg \
#	  -c "program $< 0x08000000 verify reset exit"

.PHONY: all size clean test
