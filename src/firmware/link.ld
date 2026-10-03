OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0, LENGTH = 64K }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text .text.*) } > ram
    .rodata : { *(.rodata .rodata.*) } > ram
    .data : {
        . = ALIGN(4);
        __global_pointer$ = . + 0x800;
        *(.sdata .sdata.* .data .data.*)
    } > ram
    .bss (NOLOAD) : {
        . = ALIGN(4); __bss_start = .;
        *(.sbss .sbss.* .bss .bss.* COMMON)
        . = ALIGN(4); __bss_end = .;
    } > ram
    __stack_top = ORIGIN(ram) + LENGTH(ram);
    ASSERT(__bss_end <= __stack_top - 8192, "Less than 8 KiB left for stack")
}
