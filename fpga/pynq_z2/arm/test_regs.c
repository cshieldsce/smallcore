/* Step 1 of the ARM host: ARM -> M_AXI_GP0 -> AXI3 to AXI4-Lite -> AXI clock converter ->
 * smallcore_axi.v on the SmallCore clock. Reads ID and VERSION, writes patterns to SCRATCH and
 * reads them back, prints PASS or FAIL on UART0. The verdict and the error count also go to
 * `result` in OCM, which run_arm.tcl reads over JTAG, so the test stands without the UART too. */
#include <stdint.h>
#include "uart.h"

#define SC_BASE     0x43C00000u
#define SC(off)     (*(volatile uint32_t *)(SC_BASE + (off)))
#define SC_ID       0x00
#define SC_VERSION  0x04
#define SC_SCRATCH  0x08

#define SC_ID_MAGIC 0x53434F52u

volatile uint32_t result[4];    /* [0] 0x600DC0DE pass / 0xBAD0BAD0 fail, [1] errors, [2] ID, [3] VERSION */

static uint32_t errors;

static void check(const char *what, uint32_t got, uint32_t want)
{
    uart_puts(got == want ? "  ok   " : "  FAIL ");
    uart_puts(what);
    uart_puts(" = 0x");
    uart_hex(got);
    if (got != want) {
        uart_puts(", want 0x");
        uart_hex(want);
        errors++;
    }
    uart_puts("\n");
}

int main(void)
{
    static const uint32_t patterns[] = {
        0x00000000u, 0xFFFFFFFFu, 0xA5A5A5A5u, 0x5A5A5A5Au,
        0x12345678u, 0x80000001u, 0xDEADBEEFu, 0x01234567u,
    };

    uart_init();
    uart_puts("\nsmallcore_axi step 1: ID / VERSION / SCRATCH\n");

    uint32_t id = SC(SC_ID), version = SC(SC_VERSION);
    check("ID", id, SC_ID_MAGIC);
    uart_puts("  VERSION = 0x");
    uart_hex(version);
    uart_puts("  (ABI ");
    uart_hex(version >> 16);
    uart_puts(", CORE_DIV ");
    uart_hex(version & 0xFF);
    uart_puts(")\n");
    if ((version >> 16) != 1) { uart_puts("  FAIL ABI version\n"); errors++; }

    for (unsigned i = 0; i < sizeof patterns / sizeof patterns[0]; i++) {
        SC(SC_SCRATCH) = patterns[i];
        check("SCRATCH", SC(SC_SCRATCH), patterns[i]);
    }
    /* 1000 more, address-dependent values, each written then read */
    uint32_t bad = 0;
    for (uint32_t i = 0; i < 1000; i++) {
        uint32_t v = i * 0x9E3779B9u;
        SC(SC_SCRATCH) = v;
        if (SC(SC_SCRATCH) != v) bad++;
    }
    check("SCRATCH 1000-write sweep mismatches", bad, 0);

    result[1] = errors;
    result[2] = id;
    result[3] = version;
    result[0] = errors ? 0xBAD0BAD0u : 0x600DC0DEu;
    uart_puts(errors ? "RESULT FAIL\n" : "RESULT PASS\n");
    return 0;
}
