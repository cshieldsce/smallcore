# SmallCore on the PYNQ-Z2

Two builds. The first is the smoke test below, with buttons as the host. The second, [The ARM as the host](#the-arm-as-the-host), puts Linux on the Zynq in that role.

The FPGA smoke test: `rtl/smallcore.v`, the chip-level design with its program ROM and host register bus, in a wrapper where the board's buttons are the host and the LEDs are the read data. With a jumper across two PMOD pins the SPI master talks to itself, and the byte the host wrote comes back.

```
smallcore_pynq.v   the wrapper: 125 MHz / 4 core clock, debounced buttons -> bus transactions, LEDs <- host_rdata, PMOD A <- the four pads
pynq_z2.xdc        pins: sysclk H16, SW, BTN, LD0..3, LD4/LD5 RGB, PMOD A pins 1..4
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

In Vivado, any recent version:

1. Create an RTL project for part `xc7z020clg400-1` (the PYNQ-Z2's Zynq-7020).
2. Add design sources: `fpga/pynq_z2/smallcore_pynq.v` and the seven files in `rtl/`: `smallcore.v`, `host.v`, `rom.v`, `ram.v`, `top.v`, `core.v`, `fifo.v`. Set `smallcore_pynq` as top.
3. Add `fpga/pynq_z2/pynq_z2.xdc` as a constraint. Check its pins against your board's master XDC; the switch, button, LED and PMOD pins are those of the PYNQ base overlay, the 125 MHz clock on H16 is from the TUL master file.
4. Generate Bitstream. The XDC declares the divided clock as a generated clock, so the core's paths are timed at 32 ns; check the timing summary reports no unconstrained paths and no failing endpoints.
5. Program the device from Hardware Manager over USB-JTAG, or copy the `.bit` to the board and load it from Python with `pynq.Overlay` (it also wants a `.hwh`; the export step in Vivado writes one).

## Run

1. Put a jumper between PMOD A pin 1 and pin 4 (MOSI to MISO). Nothing else on the PMOD.
2. Press BTN3. With SW1 up the LEDs read `101`: halted, RX empty.
3. Press BTN0. LEDs read `001`: running, stalled on PULL, waiting for a byte.
4. Press BTN1. The frame goes out on pins 1..3 and comes back on pin 4. LEDs read `100`: halted, a byte in the RX FIFO.
5. SW1 down: LEDs read `0x96`, LD1, LD2, LD4 red and LD5 red on.
6. Press BTN2 to pop. SW1 up reads `101` again.

To run again press BTN0 again: the byte you push after that goes out. Bytes pushed before a restart stay queued; only BTN3 clears the FIFOs. With SW0 up, BTN0 selects the LSB-first program; through a loopback both bit orders return the byte unchanged, which is why the RTL test with a slave model, `tests/rtl/test_smallcore.py`, is the one that proves the bit order.

What it proves: the program came from the on-chip ROM, the byte went through the host register block into the real TX FIFO, out of the pads as an SPI frame, back in through the pad readback, the input shift register, PUSH and the RX FIFO, and out through the register block, on hardware, with nothing but buttons for a host.

# The ARM as the host

The next step after the button smoke test: Linux on the Zynq's ARM drives SmallCore's host bus through AXI. SmallCore is unchanged and so is its host protocol; only the thing making the strobes changed.

```
Linux, Python: smallcore.py         SmallCore, its driver and command line
      | AXI4-Lite, M_AXI_GP0 at 0x43C00000
axi_host.v                          one CMD register write = one host bus strobe, timed in core clocks
      | host_addr, host_wdata, host_we, host_re, host_rdata
rtl/smallcore.v                     unchanged: host.v, rom.v, ram.v, top.v
      | gpio[3:0]
PMOD A pins 1..4, LD0..LD3, the ILA
```

```
axi_host.v              the bridge: AXI4-Lite slave, strobe sequencer, the core clock enable
smallcore_axi.v         axi_host + a BUFGCE core clock + rtl/smallcore.v, the unit the bench tests
smallcore_pynq_axi.v    the board top: the block design, smallcore_axi, IOBUFs, LEDs, the ILA
create_project_axi.tcl  the Vivado project: block design (PS7, FCLK_CLK0 100 MHz, SmartConnect, M_AXI), ILA IP, RTL
pynq_z2_axi.xdc         LEDs and PMOD A, with pull-ups on the PMOD pins
smallcore.py            the driver, SmallCore(regs), and the `smallcore` command
```

The core runs on FCLK_CLK0 gated by a clock enable, one edge every CLKDIV cycles: 100 MHz / 4 = 25 MHz out of reset, `smallcore clkdiv N` to change it. The bridge counts strobes in core clocks, so the host timing holds at any CLKDIV. The cost is that a CMD write, and a PEEK or LAST read behind it, holds the ARM's bus access for up to 11 core clocks, so talk to the core at a fast CLKDIV. Keep CLKDIV at 2 or more on the board: the pads are not timed, and led_byte.asm reads pad 0 back one core clock after driving it. `python -m pytest tests/rtl/test_pynq_axi.py -v` runs `smallcore_axi.v` under Verilator with `smallcore.py` itself as the host, its register accesses turned into AXI transactions by the bench, and checks every step below: the strobe timing at CLKDIV 1, 3 and 7; slot 8 through the jumper at CLKDIV 1, 4 and 13; an uploaded SPI program with a slave; I²C with a slave that ACKs and with nothing on the bus; both LED programs.

## Registers

| offset | name | access |
|---|---|---|
| 0x00 | ID | R: `0x534D4331`, "SMC1" |
| 0x04 | CTRL | W bit 0: hard reset of SmallCore. R: `{core_reset, busy}` |
| 0x08 | CLKDIV | RW: aclk cycles per core clock, 4 out of reset, 0 is taken as 1 |
| 0x0C | CMD | W: one host transaction, `[7:0]` wdata, `[9:8]` addr, `[16]` we, `[17]` re, exactly one of the two. The AXI write waits while the last one is in flight |
| 0x10 | LAST | R: `host_rdata` as the last strobe rose, so after an RX_DATA `re` the byte popped. Waits for the transaction to finish |
| 0x14 | PADS | R: `{gpio_in, gpio_oe, gpio_out}` in `[11:8]`, `[7:4]`, `[3:0]` |
| 0x20..0x2C | PEEK0..3 | R: `host_rdata` at host address 0..3, no strobe: 0x24 is RX_DATA, 0x28 STATUS, 0x2C CONTROL |

A strobe is held 6 core clocks high and 4 low (host.v asks for 4 and 3), with `host_addr` and `host_wdata` set a core clock before it rises and held until the low time is over.

## Build

```
vivado -mode batch -source fpga/pynq_z2/create_project_axi.tcl -tclargs build
```

This writes `build/pynq_z2_axi/overlay/`: `smallcore.bit`, `smallcore.hwh` and `smallcore.ltx`. With the TUL board files installed, the PS7 gets the PYNQ-Z2 preset. Without them it gets only what the design needs: GP0, FCLK_CLK0 at 100 MHz and its reset. That is enough for `pynq.Overlay`, because Linux has already set up the PS. Check `build/pynq_z2_axi/timing_summary.rpt` for failing endpoints.

## On the board

Copy the repository to the board, e.g. `/home/xilinx/smallcore`, and the three overlay files into it. Everything below runs as root in the PYNQ image's Python (`sudo -i`), because `/dev/mem` and `pynq` need it; `pyyaml` is only needed to assemble `.asm` files there.

```
ln -s /home/xilinx/smallcore/fpga/pynq_z2/smallcore.py /usr/local/bin/smallcore
smallcore overlay /home/xilinx/smallcore/build/pynq_z2_axi/overlay/smallcore.bit   # programs the PL, sets FCLK0
smallcore id                     # 0x534d4331
smallcore reset
smallcore status                 # halted=1 tx_full=0 rx_empty=1 control=0x00
```

LD5 red blinks about 1.5 times a second when the PL is clocked. LD4 green is SmallCore out of reset. LD4 blue flickers with each host bus strobe. LD0..LD3 always show the four pads.

From Python:

```python
import sys; sys.path.insert(0, "/home/xilinx/smallcore/fpga/pynq_z2")
from smallcore import SmallCore
sc = SmallCore.open()
sc.load("programs/spi/spi_duplex_msb.asm"); sc.run()
sc.write(0x96); sc.wait_halted(); hex(sc.read())
```

### 1. LEDs driven by the core

Nothing on the PMOD. `programs/led/` has two programs. They go into the program RAM because the ROM has no free slot.

```
smallcore clkdiv 4
smallcore load programs/led/led_blink.asm
smallcore clkdiv 100000          # 1 kHz core clock
```

LD0, LD1, LD2 and LD3 light one at a time, about a second each, with no host involvement after the load. `smallcore clkdiv 10000` makes it ten times faster; `smallcore pads` shows the pin levels. Load at a fast CLKDIV and slow down afterwards. A strobe lasts 11 core clocks, and the ARM's AXI access waits for it: 11 ms each at 1 kHz.

```
smallcore clkdiv 4
smallcore load programs/led/led_byte.asm
smallcore tx 05                  # LD0 and LD2
smallcore tx 0a                  # LD1 and LD3
smallcore tx 0f                  # all four
```

Each byte's low nibble goes on the four pins. The core has no four-pin write, so the byte goes through the accumulator (see the program's comments). Pin 0 flickers for 26 core clocks per byte, about 1 µs at CLKDIV 4, and pad 0 must read back high, so leave PMOD pin 1 free.

### 2. SPI, checked on the ILA

1. Put a jumper from PMOD A pin 1 to pin 4 (MOSI to MISO).
2. Connect Vivado Hardware Manager to the board over USB-JTAG. Open target, but do not program the device: pynq already did. Refresh the device and give it `smallcore.ltx` as the probes file. `hw_ila_1` appears.
3. Trigger on the TX_DATA write: `probe4` (host_we) = 1 and `probe3` (host_addr) = 0, trigger position 100 of 8192. Arm it.
4. Send the byte and read it back:

   ```
   smallcore clkdiv 4
   smallcore load programs/spi/spi_duplex_msb.asm    # or: smallcore select 8, the same program from the ROM
   smallcore tx 96
   smallcore rx                                      # 96
   ```

On the ILA, `probe0` is the pads: bit 2 is CS, bit 1 SCLK, bit 0 MOSI and bit 3 MISO. CS falls a few core clocks after the strobe. SCLK then rises 8 times, one period every 8 core clocks (32 samples, 3.125 MHz). MOSI on the rises reads 1,0,0,1,0,1,1,0 (0x96, MSB first), and MISO follows it through the jumper. CS rises as the byte is pushed. Then an RX_DATA `re` strobe (probe5) pops it after `smallcore rx`; arm again with `probe5` = 1 to catch it, with `probe7` (host_rdata) showing 0x96. At CLKDIV 1 the frame is 4 times shorter; the ILA always samples at 100 MHz.

With a real SPI device instead of the jumper: MOSI pin 1, SCLK pin 2, CS pin 3, MISO pin 4, mode 0.

### 3. I²C, checked on the ILA

Nothing on the PMOD. The XDC's pull-ups hold SDA (pin 1) and SCL (pin 2) high, so the bus is idle.

```
smallcore reset
smallcore load programs/i2c/i2c_write_addr_data.asm
smallcore tx a0 3c               # address 0x50 write, then one data byte
smallcore rx                     # 01: NACK, nobody at 0x50
smallcore status                 # halted=1; the data byte 3c is still queued, as the program says
```

On the ILA, with the same trigger, `probe0` bit 0 is SDA and bit 1 is SCL. The sequence is: START (SDA falls while SCL is high), 8 clocks of 1,0,1,0,0,0,0,0, then the ninth clock with SDA high (`probe2` bit 0, gpio_oe, is low: the master has let go), then STOP (SDA rises while SCL is high). A clock is 8 core clocks.

With a device on the bus, for example an EEPROM at 0x50 or any sensor at its address, with its own pull-ups to 3.3 V: `smallcore tx <addr<<1> <byte>`, then `smallcore rx -n 2` reads `00 00`, both ACKed, and the ILA shows SDA held low by the device on both ninth clocks. The PMOD's internal pull-ups are weak (tens of kΩ), fine for the ILA, but slow for a real bus above a few tens of kHz: use real pull-ups, or CLKDIV 100 for about 125 kHz.
