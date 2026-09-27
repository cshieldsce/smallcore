<!---
Tiny Tapeout datasheet source. The architecture, simulator, assembler and tests live in the SmallCore repository root.
-->

## How it works

SmallCore is a PIO-style programmable protocol peripheral. A program of 16-bit words runs one word per cycle plus a per-word delay; each word can shift a bit out or in, move a byte between a shift register and a FIFO, wait on an input level, skip on a bit of the received byte, jump, or set configuration, and every word can drive one GPIO pin as a side effect on the same edge. Eleven programs, UART TX and RX, SPI mode 0 in both bit orders with and without receive, and I²C master writes, are in an on-chip ROM; the host picks one by number.

The host talks to four registers over `ui` (write data), `uo` (read data) and `uio[7:4]` (address on 5:4, write strobe on 6, read strobe on 7). A strobe is taken as a rising edge, held at least 3 clocks high and 3 low, and low for 3 clocks after reset before the first one.

| addr | write | read |
|---|---|---|
| 0 TX_DATA | push the byte into the TX FIFO (dropped if full) | 0 |
| 1 RX_DATA | – | RX FIFO head; the read strobe pops it |
| 2 STATUS | – | bit 2 halted, bit 1 tx_full, bit 0 rx_empty |
| 3 CONTROL | select program slot (bits 3:0) and restart the core at pc 0; the FIFOs keep their bytes | the slot |

Slots: 0 none (halted), 1 uart_tx_0x55, 2 uart_tx_pull, 3 uart_tx_loop, 4 uart_rx, 5 spi_tx_lsb, 6 spi_tx_msb, 7 spi_duplex_lsb, 8 spi_duplex_msb, 9 i2c_write, 10 i2c_write_stretch, 11 i2c_write_addr_data. Reset selects slot 0 and clears both FIFOs.

`uio[3:0]` are the four protocol pads, `gpio[3:0]`: a program drives them push-pull or open-drain and reads them back. SPI uses 0 MOSI, 1 SCLK, 2 CS, 3 MISO; UART uses 0; I²C uses 0 SDA, 1 SCL.

## How to test

1. Reset, then hold the strobes low for 3 clocks. `uo` with `uio[5:4] = 2` reads STATUS = 0b101: halted, RX empty.
2. Write CONTROL = 8: `ui = 8`, `uio[5:4] = 3`, raise `uio[6]` for 3 clocks, drop it. STATUS now reads 0b001: running, stalled on PULL.
3. Write TX_DATA = 0x96: `ui = 0x96`, `uio[5:4] = 0`, pulse `uio[6]`. One SPI frame leaves on `uio[0..2]`, 8 clocks per bit, MSB first.
4. Poll STATUS until bit 2 is set. RX_DATA (`uio[5:4] = 1`) reads the byte the slave sent on `uio[3]`; pulse `uio[7]` to pop it.

`test/` holds a cocotb smoke test of steps 1 and 2 against the wrapper. The cycle-accurate tests run against the Python golden model in the repository root (`make test`).

## External hardware

A mode 0 SPI slave on `uio[0..3]`, or a jumper from `uio[0]` (MOSI) to `uio[3]` (MISO) to read back the byte written. A host with 8 outputs, 8 inputs and 4 outputs for the bus: an MCU, or the FPGA wrapper in `fpga/pynq_z2/`.
