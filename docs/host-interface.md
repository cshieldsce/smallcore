# Host interface


`rtl/smallcore.v` is SmallCore packaged as a peripheral: `host.v`, a four-register bus, `rom.v`, every program in `programs/manifest.txt` at its slot, and `top.v`. A host selects a program by number, queues bytes, runs it, watches for completion and reads the result, with nothing outside the chip supplying instructions. The Tiny Tapeout wrapper maps the ports onto the 24 pins one for one:

| signal | dir | width | Tiny Tapeout pin |
|---|---|---|---|
| `host_wdata` | in | 8 | `ui[7:0]` |
| `host_rdata` | out | 8 | `uo[7:0]` |
| `host_addr`, `host_we`, `host_re` | in | 2, 1, 1 | `uio[5:4]`, `uio[6]`, `uio[7]` as inputs |
| `gpio[3:0]` | bidir | 4 | `uio[3:0]`: `gpio_out` drives when `gpio_oe`, `gpio_in` is the pad readback |

`host_rdata` continuously shows the register `host_addr` selects. A write happens on the rising edge of `host_we`, a pop on the rising edge of `host_re`, each decoded against `host_addr` at that moment:

| addr | write (`host_we` rises) | read (`host_rdata`) |
|---|---|---|
| 0 TX_DATA | push `host_wdata` into the TX FIFO; dropped if full, check STATUS first | 0 |
| 1 RX_DATA | – | RX FIFO head, 0 while empty; `host_re` rising here pops it, nothing if empty |
| 2 STATUS | – | `{5'b0, halted, tx_full, rx_empty}` |
| 3 CONTROL | `sel <= host_wdata[3:0]`, the core restarts at pc 0 in that slot; both FIFOs keep their bytes | `{4'b0, sel}` |

Rules: a strobe is held at least 4 clocks high and 3 low between strobes, and low for 3 clocks after reset before the first one; `host_wdata` and `host_addr` are set before it rises and held until it falls (the transaction decodes them from the pins two clocks after the strobe is first captured, so 4 high leaves a clock of margin whatever the strobe's phase). `RX_DATA` reads 0 while the RX FIFO is empty. Exactly one push, pop or select happens per rising edge, so a host on GPIO pins, an MCU or a button, works. Hard reset clears the core, both FIFOs and `sel`, and slot 0 is no program: a fresh chip sits halted with every pad driven high until the host selects. A CONTROL write while a program runs is an abort and restart, a defined thing: the core resets, its pads return to their reset levels, the FIFOs are untouched, even on the clock a PULL or PUSH was about to act, so a byte queued behind the one in flight goes out on the next run. `halted` says execution finished, not that the protocol succeeded; the RX FIFO says what happened (an I²C program halts after a NACK too, with the ACK bit pushed for the host to read).

| slot | program | slot | program | slot | program |
|---|---|---|---|---|---|
| 0 | none, halted | 4 | `uart_rx` | 8 | `spi_duplex_msb` |
| 1 | `uart_tx_0x55` | 5 | `spi_tx_lsb` | 9 | `i2c_write` |
| 2 | `uart_tx_pull` | 6 | `spi_tx_msb` | 10 | `i2c_write_stretch` |
| 3 | `uart_tx_loop` | 7 | `spi_duplex_lsb` | 11 | `i2c_write_addr_data` |

Slots are permanent: a program keeps its number. 12..15 were taken 2026-09-28 for the SWD read in REPEAT form, CAN stage 6A, the CAN receiver with the CRC in the core and the destuffing receiver on the accumulator, so the chip carries programs that use REPEAT, the run test and the accumulator; no slot is free, and an unnamed one would read as slot 0. `rom.v` is one lookup on `{sel, addr}`, so every program keeps its own addresses from 0 and `JMP` targets need no relocation; the 272-word library of v1.1 cost about as much as one FIFO. Because `gpio_in[k]` is the readback of pad `k` and every pad is push-pull high out of reset, a program that listens on a pin lets go of it first, the way the I²C programs always did: `uart_rx` opens with `CONFIG open_drain01, 1`, the SPI duplex programs with `CONFIG open_drain23, 2`.

