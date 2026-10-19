/* CAN against another node, the ARM as SmallCore's host (smallcore.c), PMOD A, the bitrate the
 * bitstream's CORE_DIV gives (125 kbit/s at 8):
 *   mode 1  receive, ROM slot 15 (can_rx_bytes), re-armed after each frame for `seconds`: each frame
 *           ACKed by SmallCore and its 6 destuffed bytes printed ("RX b0 .. b5") for the PC to decode
 *           with can_ref.py; checked here only against 0x123 [5A]'s stream when rx_check is set
 *   mode 2  transmit, ROM slot 13 (can_tx_crc): `tx_count` frames of ID tx_id, data tx_data, one
 *           every tx_period_ms (or until `seconds`), each acked or not
 *   mode 3  receive, ROM slot 14 (can_rx_crc), re-armed after each frame: SmallCore checks the CRC
 *           itself (a residue of 0, 0); the frame's bits are rebuilt into ID, DLC and data
 *   mode 4  transmit sweep: mode 2 for each (ID, data) in `sweep`, tx_count frames each (default 10),
 *           chosen for bit stuffing: all-dominant, all-recessive and alternating fields
 * The volatile parameters can be set by run_arm.tcl before the run. result: [0] 0x600DC0DE when
 * there was at least one frame and none bad, 0xBAD0BAD0 otherwise; [1] good; [2] bad; [3] mode. */
#include <stdint.h>
#include "uart.h"
#include "smallcore.h"

/* in .data, not .bss: start.S zeroes .bss after run_arm.tcl has written them */
#define PARAM __attribute__((section(".data")))
PARAM volatile uint32_t mode = 1;
PARAM volatile uint32_t seconds = 30;
PARAM volatile uint32_t tx_id = 0x123;
PARAM volatile uint32_t tx_data = 0x5A;
PARAM volatile uint32_t tx_count = 0;           /* 0: until `seconds` (mode 4: 10 each) */
PARAM volatile uint32_t tx_period_ms = 500;
PARAM volatile uint32_t rx_check = 1;           /* mode 1: compare with 0x123 [5A]'s stream */
PARAM volatile uint32_t quiet = 0;              /* 1: print only bad frames and the totals */
volatile uint32_t result[4];

static const uint16_t sweep[][2] = {
    { 0x000, 0x00 }, { 0x7FF, 0xFF }, { 0x123, 0x5A }, { 0x5A3, 0xA5 },
    { 0x555, 0x55 }, { 0x2AA, 0xAA }, { 0x7F0, 0x0F }, { 0x00F, 0xF0 },
};

static const uint8_t poly[2] = { 0x32, 0x8B };   /* CRC-15 0x4599 for can_tx_crc / can_rx_crc */

static void hex8(uint32_t v) { uart_putc("0123456789ABCDEF"[(v >> 4) & 0xF]); uart_putc("0123456789ABCDEF"[v & 0xF]); }
static void hex12(uint32_t v) { uart_putc("0123456789ABCDEF"[(v >> 8) & 0xF]); hex8(v); }

static void dec(uint32_t v)
{
    char b[11];
    int i = 10;
    b[i] = 0;
    do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v);
    uart_puts(b + i);
}

/* {SOF, ID10, ID9, 00000}, ID[8:1], {ID0, RTR, IDE, r0, DLC 1} */
static void can_header(uint32_t id, uint8_t h[3])
{
    h[0] = (uint8_t)(((id >> 9) & 3) << 5);
    h[1] = (uint8_t)((id >> 1) & 0xFF);
    h[2] = (uint8_t)(((id & 1) << 7) | 1);
}

static int wait_bytes(uint8_t *buf, int want, uint64_t end)
{
    int n = 0;
    while (n < want && sc_now_us() < end) n += sc_rx(buf + n, (unsigned)(want - n));
    return n;
}

static uint32_t good, bad;

/* count frames of (id, d), one every tx_period_ms, until `end`; returns how many were acked */
static uint32_t transmit(uint32_t id, uint32_t d, uint32_t count, uint64_t end)
{
    uint8_t frame[6] = { poly[0], poly[1] }, b;
    uint32_t acked_n = 0;
    can_header(id, frame + 2);
    frame[5] = (uint8_t)d;
    uart_puts("\nCAN TX: slot 13, ID 0x"); hex12(id);
    uart_puts(" data 0x"); hex8(d); uart_puts(", every "); dec(tx_period_ms); uart_puts(" ms\n");
    for (uint32_t k = 0; (count == 0 || k < count) && sc_now_us() < end; k++) {
        uint64_t t0 = sc_now_us();
        sc_reset(SC_CTRL_RX_EN);
        SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
        sc_tx(frame, sizeof frame);
        int ok = sc_wait_prefill(sizeof frame) == SC_OK && sc_run_slot(13) == SC_OK
                 && !(sc_core_status() & SC_CORE_HALTED);
        uint32_t saved = sc_timeout_ms;
        sc_timeout_ms = 20;                          /* a frame is under 0.5 ms; acked = halted */
        int acked = ok && sc_wait_halted() == SC_OK;
        sc_timeout_ms = saved;
        int n = sc_rx(&b, 1);
        if (!quiet || !acked) {
            uart_puts(acked ? "  acked     " : "  NOT acked ");
            uart_puts("post-ACK byte ");
            if (n) hex8(b); else uart_puts("--");
            uart_puts("\n");
        }
        if (acked) { good++; acked_n++; } else bad++;
        while (sc_now_us() - t0 < (uint64_t)tx_period_ms * 1000u) ;
    }
    uart_puts("  ID 0x"); hex12(id); uart_puts(" data 0x"); hex8(d); uart_puts(": acked "); dec(acked_n); uart_puts("\n");
    sc_reset(0);
    return acked_n;
}

int main(void)
{
    static const uint8_t want15[6] = { 0x12, 0x30, 0x2B, 0x41, 0x26, 0x01 };
    uint8_t buf[64];

    uart_init();
    if (sc_init() != SC_OK) { uart_puts("\nno smallcore_axi\nRESULT FAIL\n"); result[0] = 0xBAD0BAD0u; return 0; }
    uint64_t end = sc_now_us() + (uint64_t)seconds * 1000000u;

    if (mode == 1) {
        uart_puts("\nCAN RX: slot 15, re-armed after each frame\n");
        while (sc_now_us() < end) {
            sc_reset(SC_CTRL_RX_EN);
            SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
            if (sc_run_slot(15) != SC_OK) { uart_puts("  RUN timed out\n"); bad++; break; }
            if (wait_bytes(buf, 6, end) < 6) break;
            int ok = 1;
            if (rx_check) for (int i = 0; i < 6; i++) ok &= buf[i] == want15[i];
            if (!quiet || !ok) {
                uart_puts(ok ? "  RX" : "  RX BAD");
                for (int i = 0; i < 6; i++) { uart_putc(' '); hex8(buf[i]); }
                uart_puts("\n");
            }
            if (ok) good++; else bad++;
        }
    }
    else if (mode == 2) {
        transmit(tx_id, tx_data, tx_count, end);
    }
    else if (mode == 4) {
        for (unsigned p = 0; p < sizeof sweep / sizeof sweep[0]; p++)
            transmit(sweep[p][0], sweep[p][1], tx_count ? tx_count : 10, end);
    }
    else if (mode == 3) {
        uart_puts("\nCAN RX: slot 14 (can_rx_crc), SmallCore checks the CRC, re-armed after each frame\n");
        while (sc_now_us() < end) {
            sc_reset(SC_CTRL_RX_EN);
            SC_REG(SC_COMMAND) = SC_CMD_RX_CLEAR;
            sc_tx(poly, 2);
            sc_wait_prefill(2);
            if (sc_run_slot(14) != SC_OK) { uart_puts("  RUN timed out\n"); bad++; break; }
            if (wait_bytes(buf, 44, end) < 44) break;
            /* 42 stream bits, one a byte: SOF, ID[10:0], RTR, IDE, r0, DLC[3:0], data[7:0], CRC[14:0] */
            uint32_t id = 0, dlc = 0, data = 0;
            for (int i = 1; i <= 11; i++) id = id << 1 | (buf[i] & 1);
            for (int i = 15; i <= 18; i++) dlc = dlc << 1 | (buf[i] & 1);
            for (int i = 19; i <= 26; i++) data = data << 1 | (buf[i] & 1);
            int ok = (buf[0] & 1) == 0 && buf[42] == 0 && buf[43] == 0 && dlc == 1;
            if (!quiet || !ok) {
                uart_puts(ok ? "  RX CRC ok  ID 0x" : "  RX BAD     ID 0x");
                hex12(id); uart_puts(" DLC "); dec(dlc);
                uart_puts(" data 0x"); hex8(data);
                uart_puts(" residue "); hex8(buf[42]); uart_putc(' '); hex8(buf[43]);
                uart_puts("\n");
            }
            if (ok) good++; else bad++;
        }
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
