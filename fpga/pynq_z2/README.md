# SmallCore on the PYNQ-Z2

The FPGA smoke test: `rtl/smallcore.v`, the chip-level design with its program ROM and host register bus, in a wrapper where the board's buttons are the host and the LEDs are the read data. With a jumper across two PMOD pins the SPI master talks to itself, and the byte the host wrote comes back.

```
smallcore_pynq.v   the wrapper: 125 MHz / 4 core clock, debounced buttons -> bus transactions, LEDs <- host_rdata, PMOD A <- the four pads
pynq_z2.xdc        pins: sysclk H16, SW, BTN, LD0..3, LD4/LD5 RGB, PMOD A pins 1..4
create_project.tcl the Vivado project, and with -tclargs build the bitstream
program.tcl        loads a bitstream over USB-JTAG, the ILA build with -tclargs ila
build_ila.tcl      the same design with an ILA on the pads and host_rdata, non-project
ila_capture.tcl    triggers on CS falling and writes the capture to CSV
decode_capture.py  the SPI frame in that CSV as MOSI and MISO bytes
```

The wrapper is verified in simulation before Vivado sees it: `python -m pytest tests/rtl/test_pynq.py -v` runs the button sequence below under Verilator with the jumper modelled in the bench and checks the LEDs.

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

From the repository root, with Vivado on the path (any recent version for the plain build):

```
vivado -mode batch -source fpga/pynq_z2/create_project.tcl -tclargs build
vivado -mode batch -source fpga/pynq_z2/program.tcl
```

The first creates `build/pynq_z2` for part `xc7z020clg400-1` with `smallcore_pynq.v`, the seven files in `rtl/` (`smallcore.v`, `host.v`, `rom.v`, `ram.v`, `top.v`, `core.v`, `fifo.v`) and `pynq_z2.xdc`, and writes `build/pynq_z2/smallcore_pynq.runs/impl_1/smallcore_pynq.bit`. Without `-tclargs build` it only creates the project, for the GUI. The XDC declares the divided clock as a generated clock, so the core's paths are timed at 32 ns; `build/pynq_z2/timing_summary.rpt` should report no unconstrained paths and no failing endpoints. Check the XDC's pins against your board's master XDC: the switch, button, LED and PMOD pins are those of the PYNQ base overlay, the 125 MHz clock on H16 is from the TUL master file.

The second loads it over the PROG/UART micro-USB and prints `DONE: 1`. The load is volatile: power cycling clears it, and so do the PROG and SRST buttons by the USB connector, which are not BTN3. If the green DONE LED goes out on its own the board is booting from SD or QSPI over it; set JP1 to JTAG. To load from Python instead, copy the `.bit` to the board and use `pynq.Overlay`; it also wants a `.hwh`, which the export step in Vivado writes.

## Run

1. Put a jumper between PMOD A pin 1 and pin 4 (MOSI to MISO). Nothing else on the PMOD.
2. Press BTN3. With SW1 up the LEDs read `101`: halted, RX empty.
3. Press BTN0. LEDs read `001`: running, stalled on PULL, waiting for a byte.
4. Press BTN1. The frame goes out on pins 1..3 and comes back on pin 4. LEDs read `100`: halted, a byte in the RX FIFO.
5. SW1 down: LEDs read `0x96`, LD1, LD2, LD4 red and LD5 red on.
6. Press BTN2 to pop. SW1 up reads `101` again.

LD3 is not a STATUS bit, so with SW1 up the four green LEDs read `0101`, `0001`, `0100`. Holding a button shows the register it writes: BTN0 lights LD3, CONTROL = 8, and BTN3 blanks the LEDs while the core is in reset. A button wants about 34 ms of steady press to count. Read data `0xFF`, every LED on with LD4 white, means MISO was high on every bit: pin 4 is floating and the jumper is not joining it to pin 1.

To run again press BTN0 again: the byte you push after that goes out. Bytes pushed before a restart stay queued; only BTN3 clears the FIFOs. With SW0 up, BTN0 selects the LSB-first program; through a loopback both bit orders return the byte unchanged, which is why the RTL test with a slave model, `tests/rtl/test_smallcore.py`, is the one that proves the bit order.

What it proves: the program came from the on-chip ROM, the byte went through the host register block into the real TX FIFO, out of the pads as an SPI frame, back in through the pad readback, the input shift register, PUSH and the RX FIFO, and out through the register block, on hardware, with nothing but buttons for a host.

## Debug with the ILA

When the LEDs disagree, look at the pads. `build_ila.tcl` builds the same design with an ILA clocked by the core clock, 4096 samples deep, on the four pads as read back, `gpio_out`, `gpio_oe`, `host_rdata`, reset and the host strobes:

```
vivado -mode batch -source fpga/pynq_z2/build_ila.tcl
vivado -mode batch -source fpga/pynq_z2/ila_capture.tcl
python fpga/pynq_z2/decode_capture.py
```

The ILA needs a Vivado license tier that includes debug cores: the free 2023.2 install has them, a 2026.1 BASIC license refuses `create_debug_core`. `ila_capture.tcl` loads the ILA build, arms a trigger on CS falling and prints `ARMED`; press BTN3, BTN0, BTN1 within five minutes. The capture lands in `build/pynq_z2_ila/capture.csv`, and the decoder samples MOSI and MISO on each rising SCLK while CS is low:

```
frame 0: 8 bits  MOSI 0x96  MISO 0x96
```

Synthesis renames the probes: the pads are `ja_IBUF`, `gpio_out` is `ja_OBUF`, the LEDs are the `*_OBUF` nets. To browse the waveform, open Hardware Manager, load `smallcore_pynq_ila.bit` with `smallcore_pynq_ila.ltx` as the probes file, or `program.tcl -tclargs ila` loads both.
