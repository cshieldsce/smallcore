/* CAN against another node at 125 kbit/s, the ARM as SmallCore's host (smallcore.c), PMOD A:
 *   mode 1  receive: ROM slot 15 (can_rx_bytes) over and over for `seconds`; every frame is
 *           ACKed by SmallCore, its 6 destuffed bytes printed and checked against 0x123 [5A]
 *   mode 2  transmit: ROM slot 13 (can_tx_crc) sends 0x123 [5A] every 500 ms for `seconds`,
 *           each acked or not
 * `mode` and `seconds` can be set by run_arm.tcl before the run. result: [0] 0x600DC0DE when
 * every frame received matched (mode 1) or every frame sent was acked (mode 2) and there was
 * at least one, 0xBAD0BAD0 otherwise; [1] frames good; [2] frames bad; [3] the mode. */
#include <stdint.h>
#include "uart.h"
#include "smallcore.h"

volatile uint32_t mode = 1;
volatile uint32_t seconds = 30;
volatile uint32_t result[4];

static void hex8(uint32_t v) { uart_putc("0123456789ABCDEF"[(v >> 4) & 0xF]); uart_putc("0123456789ABCDEF"[v & 0xF]); }

static void dec(uint32_t v)
{
    char b[11];
    int i = 10;
    b[i] = 0;
    do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v);
    uart_puts(b + i);
}

int main(void)
{
    static const uint8_t want[6] = { 0x12, 0x30, 0x2B, 0x41, 0x26, 0x01 };
    uint32_t good = 0, bad = 0;
    uint8_t buf[8];

    uart_init();
    if (sc_init() != SC_OK) { uart_puts("\nno smallcore_axi\nRESULT FAIL\n"); result[0] = 0xBAD0BAD0u; return 0; }
    uint64_t end = sc_now_us() + (uint64_t)seconds * 1000000u;

    if (mode == 1) {
        uart_puts("\nCAN RX: slot 15, 125 kbit/s, re-armed after each frame\n");
        while (sc_now_us() < end) {
            sc_reset(SC_CTRL_RX_EN);
            SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
            if (sc_run_slot(15) != SC_OK) { uart_puts("  RUN timed out\n"); bad++; break; }
            int n = 0;
            while (n < 6 && sc_now_us() < end) n += sc_rx(buf + n, 6 - n);
            if (n < 6) break;
            int same = 1;
            for (int i = 0; i < 6; i++) same &= buf[i] == want[i];
            uart_puts(same ? "  frame ok  " : "  frame BAD ");
            for (int i = 0; i < 6; i++) { uart_putc(' '); hex8(buf[i]); }
            uart_puts("\n");
            if (same) good++; else bad++;
        }
    }
    else {
        uart_puts("\nCAN TX: slot 13, 0x123 [5A] every 500 ms, 125 kbit/s\n");
        uint8_t frame[6] = { 0x32, 0x8B, 0x00, 0x91, 0x81, 0x5A };   /* poly, header of 0x123 DLC 1, data */
        while (sc_now_us() < end) {
            uint64_t t0 = sc_now_us();
            sc_reset(SC_CTRL_RX_EN);
            SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
            sc_tx(frame, sizeof frame);
            int ok = sc_wait_prefill(sizeof frame) == SC_OK && sc_run_slot(13) == SC_OK
                     && !(sc_core_status() & SC_CORE_HALTED);
            uint32_t saved = sc_timeout_ms;
            sc_timeout_ms = 50;                      /* a frame is ~0.4 ms; acked = halted */
            int acked = ok && sc_wait_halted() == SC_OK;
            sc_timeout_ms = saved;
            int n = sc_rx(buf, 1);
            uart_puts(acked ? "  acked     " : "  NOT acked ");
            uart_puts("post-ACK byte ");
            if (n) hex8(buf[0]); else uart_puts("--");
            uart_puts("\n");
            if (acked) good++; else bad++;
            while (sc_now_us() - t0 < 500000) ;
        }
        sc_reset(0);
    }

    uart_puts("RESULT frames good ");
    dec(good);
    uart_puts(", bad ");
    dec(bad);
    uart_puts((good && !bad) ? "\nRESULT PASS\n" : "\nRESULT FAIL\n");
    result[1] = good;
    result[2] = bad;
    result[3] = mode;
    result[0] = (good && !bad) ? 0x600DC0DEu : 0xBAD0BAD0u;
    return 0;
}
