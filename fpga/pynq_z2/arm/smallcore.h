/* Bare-metal driver for smallcore_axi.v, the SmallCore host peripheral at 0x43C0_0000, ABI v1.
 * The register map is the one in smallcore_axi.v's header; the FPGA's host engine makes every
 * SmallCore host transaction, so nothing here depends on the ARM's timing. Every wait is a
 * condition the hardware reports, bounded by sc_timeout_ms (default 1000) on the Cortex-A9's
 * global timer; a timeout returns SC_TIMEOUT. */
#ifndef SMALLCORE_H
#define SMALLCORE_H

#include <stdint.h>

#define SC_BASE            0x43C00000u
#define SC_REG(off)        (*(volatile uint32_t *)(SC_BASE + (off)))

#define SC_ID              0x00
#define SC_VERSION         0x04
#define SC_SCRATCH         0x08
#define SC_CTRL            0x0C
#define SC_STATUS          0x10
#define SC_COMMAND         0x14
#define SC_SLOT            0x18
#define SC_TX_DATA         0x1C
#define SC_TX_COUNT        0x20
#define SC_RX_DATA         0x24
#define SC_RX_COUNT        0x28
#define SC_RAW             0x2C
#define SC_CORE_STATUS     0x30
#define SC_TX_COMMITTED    0x34

#define SC_ID_MAGIC        0x53434F52u
#define SC_ABI             1u

#define SC_CTRL_RESET      (1u << 0)
#define SC_CTRL_RX_EN      (1u << 1)
#define SC_CTRL_PADS_GPIO  (1u << 2)    /* 0: CAN on PMOD A, 1: the four GPIOs on PMOD B */

#define SC_STATUS_IDLE     (1u << 0)
#define SC_STATUS_TX_FULL  (1u << 1)    /* TX staging full */
#define SC_STATUS_RX_OVF   (1u << 2)
#define SC_STATUS_RAW_DONE (1u << 3)
#define SC_STATUS_RAW_BUSY (1u << 4)
#define SC_STATUS_LOCKED   (1u << 5)
#define SC_STATUS_RUN_BUSY (1u << 6)    /* RUN not yet written, or STATUS not yet read after it */

#define SC_CMD_RUN         (1u << 0)
#define SC_CMD_RX_CLEAR    (1u << 1)
#define SC_CMD_TX_FLUSH    (1u << 2)
#define SC_CMD_COMMIT_CLR  (1u << 3)

#define SC_CORE_HALTED     (1u << 2)    /* SmallCore STATUS bits, CORE_STATUS and raw reads of addr 2 */
#define SC_CORE_TX_FULL    (1u << 1)
#define SC_CORE_RX_EMPTY   (1u << 0)

#define SC_HOST_TX_DATA    0            /* SmallCore host register addresses, for raw access */
#define SC_HOST_RX_DATA    1
#define SC_HOST_STATUS     2
#define SC_HOST_CONTROL    3

#define SC_RUN_RAM         0x10         /* CONTROL values past the ROM slots */
#define SC_LOAD_RAM        0x20

#define SC_OK              0
#define SC_TIMEOUT         (-1)
#define SC_BAD_ID          (-2)
#define SC_BAD_STATE       (-3)

extern uint32_t sc_timeout_ms;

uint64_t sc_now_us(void);                        /* the global timer, started by sc_init */
int      sc_init(void);                          /* checks ID and ABI; SC_BAD_ID otherwise */
void     sc_reset(uint32_t ctrl);                /* pulse core reset, then CTRL = ctrl (RX_EN, PADS_GPIO) */
uint32_t sc_status(void);                        /* the peripheral's STATUS */
uint32_t sc_core_status(void);                   /* SmallCore's STATUS as the engine last read it */
int      sc_run_slot(uint8_t control);           /* CONTROL = control, ahead of staged bytes; returns
                                                    once CORE_STATUS describes the program it started */
int      sc_wait_idle(void);
int      sc_wait_halted(void);
int      sc_tx(const uint8_t *bytes, unsigned n); /* stage n bytes as space allows */
int      sc_wait_prefill(unsigned n);            /* the core holds min(n, 4) of n staged bytes */
unsigned sc_tx_committed(void);
unsigned sc_rx_count(void);
int      sc_rx(uint8_t *buf, unsigned max);      /* pops what is there, up to max; the count */
int      sc_raw_read(unsigned addr, int pop);    /* the byte, or SC_TIMEOUT */
int      sc_raw_write(unsigned addr, uint8_t value);
int      sc_load_ram(const uint16_t *words, unsigned n);  /* CONTROL 0x20, the bytes, all committed */
int      sc_run_ram(void);                       /* CONTROL 0x10 */

/* Load mode lasts until the next CONTROL write: after sc_load_ram, TX_DATA still feeds the
 * program loader, so run (sc_run_ram) or reset before staging any bytes for the program. */

#endif
