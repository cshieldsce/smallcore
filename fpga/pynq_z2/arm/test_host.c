/* The ARM as SmallCore's host, through smallcore.c, on the hardware:
 *   1 ID / VERSION / ABI
 *   2 SmallCore STATUS and CONTROL by raw reads, CONTROL by RUN and by raw write
 *   3 SPI, ROM slot 8 (spi_duplex_msb), PMOD B, the jumper from pin 1 to pin 4
 *   4 the same program loaded into RAM over TX_DATA (CONTROL 0x20 / 0x10) and run
 *   5 CAN TX, ROM slot 13: 0x123 [5A] at 125 kbit/s on PMOD A; the other node must ACK
 *   6 CAN RX, ROM slot 15: waits for 0x123 [5A] from the other node, ACKs it
 * `tests` (default all) picks them, a bit each from bit 0; run_arm.tcl can set it before the
 * run. Results go out on UART0 and into `result`: [0] 0x600DC0DE all passed / 0xBAD0BAD0,
 * [1] the bitmask of tests that failed, [2] the bitmask that ran, [3] the CAN RX byte count. */
#include <stdint.h>
#include "uart.h"
#include "smallcore.h"
#include "spi_duplex_msb.h"

volatile uint32_t tests = 0x3F;
volatile uint32_t result[4];

static uint32_t failed, ran;
static int current;

static void begin(int n, const char *what)
{
    current = n;
    ran |= 1u << (n - 1);
    uart_puts("\n[");
    uart_putc('0' + n);
    uart_puts("] ");
    uart_puts(what);
    uart_puts("\n");
}

static void check(int ok, const char *what)
{
    uart_puts(ok ? "  ok   " : "  FAIL ");
    uart_puts(what);
    uart_puts("\n");
    if (!ok) failed |= 1u << (current - 1);
}

static void hex8(uint32_t v) { uart_putc("0123456789ABCDEF"[(v >> 4) & 0xF]); uart_putc("0123456789ABCDEF"[v & 0xF]); }

static void show(const char *what, uint32_t v)
{
    uart_puts("       ");
    uart_puts(what);
    uart_puts(" = 0x");
    uart_hex(v);
    uart_puts("\n");
}

static void show_bytes(const char *what, const uint8_t *b, int n)
{
    uart_puts("       ");
    uart_puts(what);
    uart_puts(":");
    for (int i = 0; i < n; i++) { uart_putc(' '); hex8(b[i]); }
    uart_puts("\n");
}

/* one byte through an SPI program (a ROM slot, or RAM): RUN, which returns with the program
 * started and waiting in PULL; the byte; the halt; the byte back through the jumper */
static int spi_step;     /* where spi_byte stopped: 1 RUN, 2 halted at once, 3 staging, 4 halt, 5 RX */

static int spi_byte(uint8_t control, uint8_t out, uint8_t *in)
{
    spi_step = 1;
    if (sc_run_slot(control) != SC_OK) return SC_TIMEOUT;
    spi_step = 2;
    if (sc_core_status() & SC_CORE_HALTED) return SC_BAD_STATE;
    spi_step = 3;
    if (sc_tx(&out, 1) != SC_OK) return SC_TIMEOUT;
    spi_step = 4;
    if (sc_wait_halted() != SC_OK) return SC_TIMEOUT;
    spi_step = 5;
    uint64_t start = sc_now_us();
    while (sc_now_us() - start < 100000)
        if (sc_rx(in, 1) == 1) return SC_OK;
    return SC_TIMEOUT;
}

static const uint8_t spi_bytes[] = { 0x96, 0x3C, 0xA5, 0x00, 0xFF };

static void test_spi(uint8_t control)
{
    for (unsigned i = 0; i < sizeof spi_bytes; i++) {
        uint8_t in = 0;
        int r = spi_byte(control, spi_bytes[i], &in);
        uart_puts("       sent 0x"); hex8(spi_bytes[i]);
        if (r == SC_OK) { uart_puts(", got 0x"); hex8(in); }
        else {
            uart_puts(", failed at step "); uart_putc('0' + spi_step);
            uart_puts(": STATUS "); uart_hex(sc_status());
            uart_puts(" CORE_STATUS "); hex8(sc_core_status());
            uart_puts(" TX_COUNT "); uart_hex(SC_REG(SC_TX_COUNT));
            uart_puts(" COMMITTED "); uart_hex(sc_tx_committed());
            uart_puts(" CONTROL "); hex8((uint32_t)sc_raw_read(SC_HOST_CONTROL, 0));
        }
        uart_puts("\n");
        check(r == SC_OK && in == spi_bytes[i], "the byte came back through the jumper");
    }
}

/* CAN 2.0A base frame header for can_tx_crc: {SOF, ID10, ID9, 00000}, ID[8:1], {ID0, RTR, IDE, r0, DLC} */
static void can_header(uint16_t id, uint8_t dlc, uint8_t h[3])
{
    h[0] = (uint8_t)(((id >> 9) & 3) << 5);
    h[1] = (uint8_t)((id >> 1) & 0xFF);
    h[2] = (uint8_t)(((id & 1) << 7) | (dlc & 0xF));
}

int main(void)
{
    uint8_t buf[64];
    int r;

    uart_init();
    uart_puts("\nsmallcore ARM host test (ABI v1)\n");

    if (tests & 1) {
        begin(1, "ID / VERSION");
        check(sc_init() == SC_OK, "ID 0x53434F52, ABI 1");
        show("VERSION", SC_REG(SC_VERSION));
        check(sc_status() & SC_STATUS_LOCKED, "MMCM locked");
    }

    if (tests & 2) {
        begin(2, "SmallCore STATUS / CONTROL over raw host transactions");
        sc_reset(0);
        r = sc_raw_read(SC_HOST_STATUS, 0);
        show("raw STATUS", (uint32_t)r);
        check(r == 0x05, "STATUS = 0x05 at slot 0 (halted, rx_empty)");
        check((uint32_t)r == sc_core_status(), "CORE_STATUS agrees");
        r = sc_raw_read(SC_HOST_CONTROL, 0);
        check(r == 0x00, "CONTROL = 0x00 after reset");
        check(sc_run_slot(7) == SC_OK, "RUN slot 7: RUN busy clears");
        check(sc_raw_read(SC_HOST_CONTROL, 0) == 7, "RUN slot 7: CONTROL = 0x07");
        check(sc_raw_write(SC_HOST_CONTROL, 0x0D) == SC_OK && sc_raw_read(SC_HOST_CONTROL, 0) == 0x0D,
              "raw write CONTROL 0x0D: CONTROL = 0x0D");
        sc_reset(0);
    }

    if (tests & 4) {
        begin(3, "SPI, ROM slot 8 (spi_duplex_msb), PMOD B, jumper pin 1 to pin 4");
        sc_reset(SC_CTRL_PADS_GPIO | SC_CTRL_RX_EN);
        SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
        test_spi(8);
    }

    if (tests & 8) {
        begin(4, "the same program loaded into RAM and run (CONTROL 0x20, bytes, 0x10)");
        sc_reset(SC_CTRL_PADS_GPIO | SC_CTRL_RX_EN);
        SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
        r = sc_load_ram(spi_duplex_msb, spi_duplex_msb_words);
        check(r == SC_OK, "load: CONTROL 0x20 done, every byte committed, engine idle");
        show("TX_COMMITTED", sc_tx_committed());
        check(sc_tx_committed() == 2 * spi_duplex_msb_words, "TX_COMMITTED = 2 x words");
        check(!(sc_core_status() & SC_CORE_TX_FULL), "the TX FIFO never filled");
        test_spi(SC_RUN_RAM);           /* each byte: CONTROL 0x10 first, which ends load mode */
        check(sc_raw_read(SC_HOST_CONTROL, 0) == SC_RUN_RAM, "CONTROL = 0x10");
    }

    if (tests & 16) {
        begin(5, "CAN TX, ROM slot 13: 0x123 [5A], 125 kbit/s, PMOD A");
        uint8_t frame[6] = { 0x32, 0x8B };          /* the CRC-15 polynomial, then the header and data */
        can_header(0x123, 1, frame + 2);
        frame[5] = 0x5A;
        sc_reset(SC_CTRL_RX_EN);
        SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
        sc_tx(frame, sizeof frame);
        r = sc_wait_prefill(sizeof frame);
        check(r == SC_OK, "prefill: TX_COMMITTED >= 4 and CORE_STATUS tx_full before RUN");
        show("TX_COMMITTED before RUN", sc_tx_committed());
        r = sc_run_slot(13);
        uint32_t cs = sc_core_status();     /* before any UART output: a frame is ~0.45 ms */
        check(r == SC_OK, "RUN slot 13: RUN busy clears");
        check(!(cs & SC_CORE_HALTED), "CORE_STATUS: slot 13 running, not slot 0's halt");
        r = sc_wait_halted();
        show("TX_COMMITTED after", sc_tx_committed());
        int n = sc_rx(buf, sizeof buf);
        show_bytes("post-ACK byte", buf, n);
        check(sc_tx_committed() == sizeof frame, "every frame byte committed");
        check(r == SC_OK, "acked: the program halted (the other node ACKed)");
    }

    if (tests & 32) {
        begin(6, "CAN RX, ROM slot 15: waiting for 0x123 [5A] from the other node");
        static const uint8_t want[6] = { 0x12, 0x30, 0x2B, 0x41, 0x26, 0x01 };
        sc_reset(SC_CTRL_RX_EN);
        SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
        check(sc_run_slot(15) == SC_OK, "RUN slot 15: RUN busy clears");
        int n = 0;
        uint64_t start = sc_now_us();
        while (n < 6 && sc_now_us() - start < 20000000) n += sc_rx(buf + n, 6 - n);
        show_bytes("RX", buf, n);
        result[3] = (uint32_t)n;
        int same = n == 6;
        for (int i = 0; i < n && i < 6; i++) same &= buf[i] == want[i];
        check(same, "RX = 12 30 2B 41 26 01, the destuffed frame");
    }

    result[1] = failed;
    result[2] = ran;
    result[0] = failed ? 0xBAD0BAD0u : 0x600DC0DEu;
    uart_puts(failed ? "\nRESULT FAIL\n" : "\nRESULT PASS\n");
    return 0;
}
