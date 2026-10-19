#include "smallcore.h"

/* the Cortex-A9 MPCore global timer: 64 bits at CPU_3x2x, 325 MHz with the PYNQ-Z2's 650 MHz APU */
#define GT_LO      (*(volatile uint32_t *)0xF8F00200u)
#define GT_HI      (*(volatile uint32_t *)0xF8F00204u)
#define GT_CTRL    (*(volatile uint32_t *)0xF8F00208u)
#define GT_MHZ     325u

uint32_t sc_timeout_ms = 1000;

uint64_t sc_now_us(void)
{
    uint32_t hi, lo;
    do { hi = GT_HI; lo = GT_LO; } while (GT_HI != hi);
    return (((uint64_t)hi << 32) | lo) / GT_MHZ;
}

static int expired(uint64_t start)
{
    return sc_now_us() - start > (uint64_t)sc_timeout_ms * 1000u;
}

static int wait_for(unsigned off, uint32_t mask, uint32_t want)
{
    uint64_t start = sc_now_us();
    while ((SC_REG(off) & mask) != want)
        if (expired(start)) return SC_TIMEOUT;
    return SC_OK;
}

int sc_init(void)
{
    GT_CTRL |= 1;                            /* timer enable */
    if (SC_REG(SC_ID) != SC_ID_MAGIC) return SC_BAD_ID;
    if ((SC_REG(SC_VERSION) >> 16) != SC_ABI) return SC_BAD_ID;
    return SC_OK;
}

void sc_reset(uint32_t ctrl)
{
    ctrl &= ~SC_CTRL_RESET;
    SC_REG(SC_CTRL) = ctrl | SC_CTRL_RESET;  /* also empties TX staging, clears TX_COMMITTED */
    SC_REG(SC_CTRL) = ctrl;
}

uint32_t sc_status(void)      { return SC_REG(SC_STATUS); }
uint32_t sc_core_status(void) { return SC_REG(SC_CORE_STATUS) & 7; }
unsigned sc_tx_committed(void) { return SC_REG(SC_TX_COMMITTED) & 0xFFFF; }
unsigned sc_rx_count(void)    { return SC_REG(SC_RX_COUNT) & 0xFFFF; }

int sc_run_slot(uint8_t control)
{
    SC_REG(SC_SLOT) = control;
    SC_REG(SC_COMMAND) = SC_CMD_RUN;
    return wait_for(SC_STATUS, SC_STATUS_RUN_BUSY, 0);
}

int sc_wait_idle(void)   { return wait_for(SC_STATUS, SC_STATUS_IDLE, SC_STATUS_IDLE); }
int sc_wait_halted(void) { return wait_for(SC_CORE_STATUS, SC_CORE_HALTED, SC_CORE_HALTED); }

int sc_tx(const uint8_t *bytes, unsigned n)
{
    for (unsigned i = 0; i < n; i++) {
        if (wait_for(SC_STATUS, SC_STATUS_TX_FULL, 0) != SC_OK) return SC_TIMEOUT;
        SC_REG(SC_TX_DATA) = bytes[i];
    }
    return SC_OK;
}

/* Before RUN: the engine has completed min(n, 4) TX_DATA transactions, and with n >= 4 the
 * core itself reports its FIFO full. Assumes TX_COMMITTED was cleared before the n bytes. */
int sc_wait_prefill(unsigned n)
{
    unsigned need = n < 4 ? n : 4;
    uint64_t start = sc_now_us();
    while (sc_tx_committed() < need)
        if (expired(start)) return SC_TIMEOUT;
    if (n >= 4) return wait_for(SC_CORE_STATUS, SC_CORE_TX_FULL, SC_CORE_TX_FULL);
    return SC_OK;
}

int sc_rx(uint8_t *buf, unsigned max)
{
    unsigned n = 0;
    while (n < max) {
        uint32_t v = SC_REG(SC_RX_DATA);
        if (!(v & 0x100)) break;
        buf[n++] = (uint8_t)v;
    }
    return (int)n;
}

static int raw(uint32_t request)
{
    if (wait_for(SC_STATUS, SC_STATUS_RAW_BUSY, 0) != SC_OK) return SC_TIMEOUT;
    SC_REG(SC_RAW) = request;
    if (wait_for(SC_RAW, 0x80000000u, 0x80000000u) != SC_OK) return SC_TIMEOUT;
    return (int)(SC_REG(SC_RAW) & 0xFF);
}

int sc_raw_read(unsigned addr, int pop)
{
    return raw((pop ? 1u << 17 : 0) | (addr & 3) << 8);
}

int sc_raw_write(unsigned addr, uint8_t value)
{
    int r = raw(1u << 16 | (addr & 3) << 8 | value);
    return r < 0 ? r : SC_OK;
}

/* CONTROL 0x20, completed; each word low byte then high through TX_DATA, which host.v's
 * loader takes instead of the TX FIFO; then every byte's transaction completed and the
 * engine idle. The caller runs it with sc_run_ram(). */
int sc_load_ram(const uint16_t *words, unsigned n)
{
    if (n > 256) return SC_BAD_STATE;
    if (sc_run_slot(SC_LOAD_RAM) != SC_OK || sc_wait_idle() != SC_OK) return SC_TIMEOUT;
    if (sc_raw_read(SC_HOST_CONTROL, 0) != SC_LOAD_RAM) return SC_BAD_STATE;
    SC_REG(SC_COMMAND) = SC_CMD_COMMIT_CLR;
    for (unsigned i = 0; i < n; i++) {
        uint8_t b[2] = { (uint8_t)words[i], (uint8_t)(words[i] >> 8) };
        if (sc_tx(b, 2) != SC_OK) return SC_TIMEOUT;
    }
    uint64_t start = sc_now_us();
    while (sc_tx_committed() != 2 * n)
        if (expired(start)) return SC_TIMEOUT;
    return sc_wait_idle();
}

int sc_run_ram(void) { return sc_run_slot(SC_RUN_RAM); }
