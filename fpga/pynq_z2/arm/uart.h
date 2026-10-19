/* PS UART0 (MIO 14..15, the PYNQ-Z2's USB UART) at 115200 8N1, polled. ps7_init has set the
 * MIO pins and the 100 MHz reference clock; uart_init sets the rest. */
#ifndef UART_H
#define UART_H

#include <stdint.h>

void uart_init(void);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_hex(uint32_t v);      /* 8 hex digits */

/* start.S's exception vectors land here: 1 undefined, 2 SVC, 3 prefetch abort, 4 data abort,
 * 6 IRQ, 7 FIQ, with the faulting address. Prints it with the fault status registers and
 * records it in exception_seen: {0xE0, n} in the top half, so run_arm.tcl's poll stops. */
extern volatile uint32_t exception_seen[3];
void exception(uint32_t n, uint32_t addr);

#endif
