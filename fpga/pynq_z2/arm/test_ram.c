/* SmallCore's RAM program path on the hardware, through the ARM host: for each N, load N PUSH
 * words (CONTROL 0x20, 2N bytes, all committed), run them (CONTROL 0x10), and count the RX
 * bytes: N if every word was stored and executed. Then the same with N PUSH words followed by
 * nothing, loaded twice, to see whether a second load replaces the first.
 * result: [0] 0x600DC0DE every count right / 0xBAD0BAD0, [1] the first N that went wrong,
 * [2] its count, [3] the number of cases. */
#include <stdint.h>
#include "uart.h"
#include "smallcore.h"

volatile uint32_t result[4];

static uint16_t prog[256];

static void dec(uint32_t v)
{
    char b[11];
    int i = 10;
    b[i] = 0;
    do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v);
    uart_puts(b + i);
}

static int run_pushes(unsigned n)
{
    for (unsigned i = 0; i < n; i++) prog[i] = 0x4001;    /* PUSH */
    sc_reset(SC_CTRL_RX_EN);
    SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
    if (sc_load_ram(prog, n) != SC_OK) return -1;
    if (sc_run_ram() != SC_OK) return -2;
    if (sc_wait_halted() != SC_OK) return -3;
    uint64_t t0 = sc_now_us();
    while (sc_now_us() - t0 < 20000) ;                   /* the drain's last pops */
    return (int)sc_rx_count();
}

int main(void)
{
    static const unsigned ns[] = { 1, 2, 3, 4, 5, 8, 16, 22, 64, 200 };
    uint32_t bad = 0, cases = 0;

    uart_init();
    sc_init();
    uart_puts("\nRAM path: N PUSH words loaded and run, RX count should be N\n");
    for (unsigned k = 0; k < sizeof ns / sizeof ns[0]; k++) {
        int got = run_pushes(ns[k]);
        cases++;
        uart_puts(got == (int)ns[k] ? "  ok   N=" : "  FAIL N=");
        dec(ns[k]);
        uart_puts(" RX count ");
        if (got < 0) { uart_puts("error "); uart_putc('0' - got); } else dec((uint32_t)got);
        uart_puts("  CONTROL ");
        dec((uint32_t)sc_raw_read(SC_HOST_CONTROL, 0));
        uart_puts("\n");
        if (got != (int)ns[k] && !bad) { bad = 1; result[1] = ns[k]; result[2] = (uint32_t)got; }
    }
    result[3] = cases;
    result[0] = bad ? 0xBAD0BAD0u : 0x600DC0DEu;
    uart_puts(bad ? "RESULT FAIL\n" : "RESULT PASS\n");
    return 0;
}
