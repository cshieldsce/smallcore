/* Bare-metal entry for the Zynq's Cortex-A9 core 0, loaded into OCM by xsdb (run_arm.tcl).
 * Caches and the MMU stay off as the boot ROM left them, so every access to the PL is a
 * strongly ordered, uncached bus transaction (and an unaligned access faults: build.py
 * compiles with -mno-unaligned-access). The vector table is at 0 (SCTLR.V = 0): reset runs
 * _start; any exception reports itself through exception() in uart.c and stops there. */
    .section .text.start
    .global _start
vectors:
    b       _start
    b       undef
    b       svc
    b       pabort
    b       dabort
    b       .
    b       irq
    b       fiq

undef:  mov r0, #1
        b   trap
svc:    mov r0, #2
        b   trap
pabort: mov r0, #3
        sub r1, lr, #4
        b   trap1
dabort: mov r0, #4
        sub r1, lr, #8
        b   trap1
irq:    mov r0, #6
        b   trap
fiq:    mov r0, #7
        b   trap
trap:   mov r1, lr
trap1:  ldr sp, =__exc_stack_top
        bl  exception
        b   .

_start:
    cpsid   if
    ldr     sp, =__stack_top
    ldr     r0, =__bss_start
    ldr     r1, =__bss_end
    mov     r2, #0
1:  cmp     r0, r1
    strlo   r2, [r0], #4
    blo     1b
    bl      main
2:  wfe
    b       2b
