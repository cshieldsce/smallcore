/* Which path corrupts bytes to SmallCore's TX_DATA: TX staging (TX_DATA register) or not.
 *   A  CAN TX 0x123 [5A], slot 13, the 6 host bytes by raw writes of SmallCore TX_DATA
 *   B  the same through TX staging (sc_tx), as can_bench.c
 *   C  4 PUSH words loaded into RAM by raw writes (CONTROL 0x20 / TX_DATA / 0x10), RX count
 *   D  the same through staging (sc_load_ram)
 * Another node on the bus must ACK for A and B. result: [0] done, [1..3] A/B acked, C/D counts. */
#include <stdint.h>
#include "uart.h"
#include "smallcore.h"

volatile uint32_t result[4];

static const uint8_t frame[6] = { 0x32, 0x8B, 0x00, 0x91, 0x81, 0x5A };

static void hex8(uint32_t v) { uart_putc("0123456789ABCDEF"[(v >> 4) & 0xF]); uart_putc("0123456789ABCDEF"[v & 0xF]); }

static int can_tx(int raw)
{
    uint8_t b;
    sc_reset(SC_CTRL_RX_EN);
    SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
    if (raw) {
        for (int i = 0; i < 4; i++) sc_raw_write(SC_HOST_TX_DATA, frame[i]);
    } else {
        sc_tx(frame, 6);
        sc_wait_prefill(6);
    }
    uart_puts(raw ? "  A raw:     " : "  B staged:  ");
    uart_puts("CORE_STATUS before RUN "); hex8(sc_core_status());
    sc_run_slot(13);
    if (raw) {                                   /* the last 2 as the program frees FIFO space */
        for (int i = 4; i < 6; i++) {
            while (sc_core_status() & SC_CORE_TX_FULL) ;
            sc_raw_write(SC_HOST_TX_DATA, frame[i]);
        }
    }
    sc_timeout_ms = 50;
    int acked = sc_wait_halted() == SC_OK;
    sc_timeout_ms = 1000;
    int n = sc_rx(&b, 1);
    uart_puts(acked ? ", ACKED" : ", not acked");
    uart_puts(", post-ACK byte "); if (n) hex8(b); else uart_puts("--");
    uart_puts("\n");
    return acked;
}

static int ram_pushes(int raw)
{
    static const uint16_t prog[4] = { 0x4001, 0x4001, 0x4001, 0x4001 };
    sc_reset(SC_CTRL_RX_EN);
    SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
    if (raw) {
        sc_raw_write(SC_HOST_CONTROL, SC_LOAD_RAM);
        for (int i = 0; i < 4; i++) {
            sc_raw_write(SC_HOST_TX_DATA, (uint8_t)prog[i]);
            sc_raw_write(SC_HOST_TX_DATA, (uint8_t)(prog[i] >> 8));
        }
        sc_raw_write(SC_HOST_CONTROL, SC_RUN_RAM);
    } else {
        sc_load_ram(prog, 4);
        sc_run_ram();
    }
    sc_wait_halted();
    uint64_t t0 = sc_now_us();
    while (sc_now_us() - t0 < 20000) ;
    int n = (int)sc_rx_count();
    uart_puts(raw ? "  C raw:     " : "  D staged:  ");
    uart_puts("4 PUSH words from RAM -> RX count ");
    uart_putc('0' + n % 10);
    uart_puts("\n");
    return n;
}

int main(void)
{
    uart_init();
    sc_init();
    uart_puts("\nTX_DATA path diagnosis\n");
    result[1] = (uint32_t)can_tx(1) | (uint32_t)can_tx(0) << 1;
    result[2] = (uint32_t)ram_pushes(1);
    result[3] = (uint32_t)ram_pushes(0);
    sc_reset(0);
    result[0] = 0x600DC0DEu;
    uart_puts("RESULT PASS\n");
    return 0;
}
