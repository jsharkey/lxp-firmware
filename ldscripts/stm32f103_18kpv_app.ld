/*
 * STM32F103 high-density, 18kPV "App" partition.
 *
 * The 18kPV factory image is an APPLICATION that runs above a ~51 KB bootloader:
 * the App's vector table lives at 0x0800C800 (direct read from the factory
 * "..._FAAB-1Bxx_..._App.hex": initial MSP 0x20000478, reset 0x0802B788), and
 * the App region tops out at the 256 KB boundary (0x08040000; top-of-image
 * "EAA1" marker at 0x0803F7FC). See docs/09-18kpv-vs-12000xp.md.
 *
 * So, unlike the monolithic 12000XP build (ldscripts/stm32f103ve.ld, vectors at
 * flash base), this script reserves the bootloader and places our App's vector
 * table at 0x0800C800. SystemInit() writes SCB->VTOR to the same address from
 * the variant descriptor, so the two stay in sync.
 *
 * NOTE: the exact bootloader size and App-region length should be re-confirmed
 * against the real part/bootloader; 0xC800 and the 256 KB top are what the
 * supplied App image implies.
 */
ENTRY(Reset_Handler)

_BOOTLOADER_SIZE = 0xC800;             /* 0x08000000 .. 0x0800C7FF reserved */

MEMORY
{
  /* App flash: from just above the bootloader up to the 256 KB boundary. */
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
