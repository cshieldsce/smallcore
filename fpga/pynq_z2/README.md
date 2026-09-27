# SmallCore on the PYNQ-Z2

The FPGA smoke test: `rtl/smallcore.v`, the chip-level design with its program ROM and host register bus, in a wrapper where the board's buttons are the host and the LEDs are the read data. With a jumper across two PMOD pins the SPI master talks to itself, and the byte the host wrote comes back.

```
smallcore_pynq.v   the wrapper: 125 MHz / 4 core clock, debounced buttons -> bus transactions, LEDs <- host_rdata, PMOD A <- the four pads
pynq_z2.xdc        pins: sysclk H16, SW, BTN, LD0..3, LD4/LD5 RGB, PMOD A pins 1..4
```

The wrapper is verified in simulation before Vivado sees it: `python -m pytest rtl_tests/test_pynq.py -v` runs the button sequence below under Verilator with the jumper modelled in the bench and checks the LEDs.

## Controls

| control | does |
|---|---|
| BTN0 | writes CONTROL: selects slot 8, `spi_duplex_msb`, or slot 7, `spi_duplex_lsb`, with SW0 up. The core restarts at pc 0 |
| BTN1 | writes TX_DATA = 0x96 |
| BTN2 | reads and pops RX_DATA |
| BTN3 | hard reset: core, FIFOs, slot 0. There is also a power-on reset |
| SW1 | down: LEDs show RX_DATA, the head of the RX FIFO. Up: LEDs show STATUS |
| LD0..LD3 | `host_rdata[3:0]` |
| LD4 red, green, blue | `host_rdata[4]`, `[5]`, `[6]` |
| LD5 red | `host_rdata[7]` |

STATUS bits: LD2 halted, LD1 tx_full, LD0 rx_empty.

PMOD A, top row: pin 1 `gpio[0]` MOSI, pin 2 `gpio[1]` SCLK, pin 3 `gpio[2]` CS, pin 4 `gpio[3]` MISO. The core runs at 31.25 MHz, so SCLK is about 3.9 MHz at 8 clocks per bit.

## Build

In Vivado, any recent version:

1. Create an RTL project for part `xc7z020clg400-1` (the PYNQ-Z2's Zynq-7020).
2. Add design sources: `fpga/pynq_z2/smallcore_pynq.v` and the six files in `rtl/`: `smallcore.v`, `host.v`, `rom.v`, `top.v`, `core.v`, `fifo.v`. Set `smallcore_pynq` as top.
3. Add `fpga/pynq_z2/pynq_z2.xdc` as a constraint. Check its pins against your board's master XDC; the switch, button, LED and PMOD pins are those of the PYNQ base overlay, the 125 MHz clock on H16 is from the TUL master file.
4. Generate Bitstream. Timing at 8 ns on `sysclk` is not close: the core runs on the divided clock.
5. Program the device from Hardware Manager over USB-JTAG, or copy the `.bit` to the board and load it from Python with `pynq.Overlay` (it also wants a `.hwh`; the export step in Vivado writes one).

## Run

1. Put a jumper between PMOD A pin 1 and pin 4 (MOSI to MISO). Nothing else on the PMOD.
2. Press BTN3. With SW1 up the LEDs read `101`: halted, RX empty.
3. Press BTN0. LEDs read `001`: running, stalled on PULL, waiting for a byte.
4. Press BTN1. The frame goes out on pins 1..3 and comes back on pin 4. LEDs read `100`: halted, a byte in the RX FIFO.
5. SW1 down: LEDs read `0x96`, LD1, LD2, LD4 red and LD5 red on.
6. Press BTN2 to pop. SW1 up reads `101` again.

To run again press BTN0 again: the byte you push after that goes out. Bytes pushed before a restart stay queued; only BTN3 clears the FIFOs. With SW0 up, BTN0 selects the LSB-first program; through a loopback both bit orders return the byte unchanged, which is why the RTL test with a slave model, `rtl_tests/test_smallcore.py`, is the one that proves the bit order.

What it proves: the program came from the on-chip ROM, the byte went through the host register block into the real TX FIFO, out of the pads as an SPI frame, back in through the pad readback, the input shift register, PUSH and the RX FIFO, and out through the register block, on hardware, with nothing but buttons for a host.
