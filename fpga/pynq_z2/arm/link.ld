/* All in the low 192 KB of on-chip memory, mapped at 0 after the boot ROM, so DDR is not needed. */
ENTRY(_start)
MEMORY { ocm (rwx) : ORIGIN = 0x00000000, LENGTH = 0x30000 }
SECTIONS {
    .text : { *(.text.start) *(.text*) *(.rodata*) } > ocm
    .data : { *(.data*) } > ocm
    .bss  : { . = ALIGN(4); __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(4); __bss_end = .; } > ocm
    . = ALIGN(8);
    . = . + 0x4000;
    __stack_top = .;
    . = . + 0x400;
    __exc_stack_top = .;
}
