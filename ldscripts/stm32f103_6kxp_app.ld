/*
 * STM32F103 high-density, EG4 6000XP "App" partition.
 *
 * Like the 12000XP 07-series, the 6000XP factory image is an APPLICATION above a
 * small bootloader: the App vector table lives at 0x08005000 (direct read from
 * "..._ccaa-xx15xx_260519.hex": initial MSP 0x2000AF88, reset 0x0802B064), the
 * low 20 KB (0x08000000..0x08004FFF) is reserved for the bootloader (all 0xFF in
 * the App image), and the App region tops at the 256 KB boundary (0x08040000;
 * signature block "SNCC…" at 0x0803F600). SystemInit writes SCB->VTOR=0x08005000
 * from the variant descriptor, so the two stay in sync. See docs/12-6000xp.md.
 *
 * NOTE: confirm the exact part (flash/RAM) and bootloader size against a unit;
 * 0x5000 and the 256 KB top are what the supplied App image implies.
 */
ENTRY(Reset_Handler)

_BOOTLOADER_SIZE = 0x5000;             /* 0x08000000 .. 0x08004FFF reserved */

MEMORY
{
  FLASH (rx) : ORIGIN = 0x08000000 + _BOOTLOADER_SIZE,
               LENGTH = 256K - _BOOTLOADER_SIZE
  RAM  (xrw) : ORIGIN = 0x20000000, LENGTH = 64K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);   /* top of stack */
_Min_Heap_Size = 0x400;
_Min_Stack_Size = 0x800;

SECTIONS
{
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } >FLASH

  .text : {
    . = ALIGN(4);
    *(.text) *(.text*)
    *(.rodata) *(.rodata*)
    *(.glue_7) *(.glue_7t) *(.eh_frame)
    KEEP(*(.init)) KEEP(*(.fini))
    . = ALIGN(4);
    _etext = .;
  } >FLASH

  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } >FLASH
  .ARM : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } >FLASH

  _sidata = LOADADDR(.data);
  .data : {
    . = ALIGN(4); _sdata = .;
    *(.data) *(.data*)
    . = ALIGN(4); _edata = .;
  } >RAM AT> FLASH

  .bss : {
    . = ALIGN(4); _sbss = .; __bss_start__ = _sbss;
    *(.bss) *(.bss*) *(COMMON)
    . = ALIGN(4); _ebss = .; __bss_end__ = _ebss;
  } >RAM

  ._user_heap_stack : {
    . = ALIGN(8);
    PROVIDE ( end = . ); PROVIDE ( _end = . );
    . = . + _Min_Heap_Size;
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  } >RAM

  /DISCARD/ : { libc.a ( * ) libm.a ( * ) libgcc.a ( * ) }
  .ARM.attributes 0 : { *(.ARM.attributes) }
}
