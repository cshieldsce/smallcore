#include "uart.h"

#define UART0       0xE0000000u
#define REG(off)    (*(volatile uint32_t *)(UART0 + (off)))
#define CR          REG(0x00)
#define MR          REG(0x04)
#define BAUDGEN     REG(0x18)
#define SR          REG(0x2C)
#define FIFO        REG(0x30)
#define BAUDDIV     REG(0x34)

#define CR_RXRST    (1u << 0)
#define CR_TXRST    (1u << 1)
#define CR_RXEN     (1u << 2)
#define CR_TXEN     (1u << 4)
#define SR_TXEMPTY  (1u << 3)
#define SR_TXFULL   (1u << 4)

void uart_init(void)
{
    CR = CR_TXRST | CR_RXRST;   /* disabled, FIFOs reset */
    MR = 0x20;                  /* 8 bits, no parity, 1 stop, reference clock undivided */
    BAUDGEN = 124;              /* 100 MHz / (124 * (6 + 1)) = 115207 baud */
    BAUDDIV = 6;
    CR = CR_TXEN | CR_RXEN;
}

void uart_putc(char c)
{
    if (c == '\n') uart_putc('\r');
    while (SR & SR_TXFULL) ;
    FIFO = (uint8_t)c;
}

void uart_puts(const char *s)
{
    while (*s) uart_putc(*s++);
    while (!(SR & SR_TXEMPTY)) ;
}

void uart_hex(uint32_t v)
{
    for (int i = 28; i >= 0; i -= 4) uart_putc("0123456789ABCDEF"[(v >> i) & 0xF]);
}

volatile uint32_t exception_seen[3];

void exception(uint32_t n, uint32_t addr)
{
    uint32_t dfsr, dfar;
    __asm__ volatile ("mrc p15, 0, %0, c5, c0, 0" : "=r"(dfsr));
    __asm__ volatile ("mrc p15, 0, %0, c6, c0, 0" : "=r"(dfar));
    exception_seen[0] = 0xE0000000u | n;
    exception_seen[1] = addr;
    exception_seen[2] = dfar;
    uart_init();
    uart_puts("\nEXCEPTION ");
    uart_hex(n);
    uart_puts(" at 0x");
    uart_hex(addr);
    uart_puts(" DFSR 0x");
    uart_hex(dfsr);
    uart_puts(" DFAR 0x");
    uart_hex(dfar);
    uart_puts("\nRESULT FAIL\n");
}
