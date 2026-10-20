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

A second wrapper puts the chip on a real CAN bus through a transceiver, with a VIO over JTAG for a host: see CAN on a real bus below. A third makes the Zynq's ARM the host, over AXI: see The Zynq ARM as the host.

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

## CAN on a real bus

The second wrapper, `smallcore_pynq_can.v`, puts the chip on a physical CAN bus through an SN65HVD230 transceiver on PMOD A and runs the ROM's CAN programs, slot 13 `can_tx_crc` and slot 15 `can_rx_bytes` (slot 14 `can_rx_crc` passes in simulation), against another CAN node. The host is a VIO driven from Tcl over JTAG.

```
smallcore_pynq_can.v   the wrapper: MMCM 125 MHz -> 8 MHz / CORE_DIV core clock, the engine below, VIO, ILAs; pad 0 split into CTX/CRX
can_host_engine.v      the FPGA-side host: 32-byte TX buffer, 256-byte RX capture, CONTROL, at 7 clocks a bus transaction
pynq_z2_can.xdc        pins: sysclk H16, LD0..3, PMOD A pin 1 CTX, pin 2 CRX (pulled up), pins 3, 4, 7 read only
build_can.tcl          non-project build with the VIO and ILA IP; -tclargs CORE_DIV (1, 2, 4, 8: 1000, 500, 250, 125 kbit/s)
can_host.tcl           Tcl procs for the host: sc_open, can_tx, can_rx_start, sc_rx_read, sc_arm/sc_save for the ILAs
can_test.tcl           the two hardware tests below, with captures
can_ref.py             an independent Classical CAN 2.0A encoder/decoder, written from the frame format, not the repo's model
can_decode.py          decodes the ILA captures with can_ref.py: fields, CRC, stuffing, delimiters, ACK, EOF, bit timing, loop delay
sim/                   xsim bench: the engine and the unmodified rtl/ through the wrapper's pad model, checked against can_ref.py
```

Wiring: PMOD A pin 1 to the transceiver's CTX (TXD), pin 2 to its CRX (RXD), pin 6 3V3, pin 5 GND. CANH/CANL to the other node, 120 Ω at each end, and a ground shared with the other node. The core drives pad 0 open-drain; the wrapper sends it to CTX and reads the wired-AND of CTX and CRX back into pad 0, as an open-drain pad on the bus would read.

The host is in the FPGA because the PC is far too slow for the chip. A VIO commit takes milliseconds, a CAN program takes a byte every 64 µs at 125 kbit/s (`can_rx_crc` pushes one every bit, 8 µs), and the FIFOs are 4 deep. `can_host_engine.v` holds the bytes and services TX_DATA, RX_DATA and STATUS at host.v's minimum strobe timing; the chip's FIFOs and ISA are unchanged. It is test infrastructure, not part of the chip.

Build, simulate, run (Vivado with debug-core support for the build; the hardware manager of any recent Vivado for the rest):

```
vivado -mode batch -source fpga/pynq_z2/build_can.tcl -tclargs 8
python fpga/pynq_z2/sim/run_sim.py --limits
vivado -mode batch -source fpga/pynq_z2/can_test.tcl -tclargs tx 8
vivado -mode batch -source fpga/pynq_z2/can_test.tcl -tclargs rx 8
python fpga/pynq_z2/can_decode.py tx build/pynq_z2_can/tx_core.csv 123 5A --loop build/pynq_z2_can/tx_loop.csv --div 8
```

`run_sim.py` runs 40 cases, IDs 0x123, 0x5A3, 0x7FF and 0x000, TX unacked and acked and both receivers through transceiver loop delays of 0 to 3 clocks, all passing; `--limits` prints where `can_tx_crc` stops working (below).

### Real CAN hardware validation

Setup: SmallCore on the PYNQ-Z2, an SN65HVD230 transceiver, a two-node bus, and CANtap's Candor firmware on a Nucleo-G474RE (FDCAN1 behind a second SN65HVD230) as the other node, at 125 kbit/s (CORE_DIV 8). 2026-10-18.

TX, slot 13 `can_tx_crc`:

- SmallCore transmitted the Classical CAN frame ID `0x123`, DLC `1`, data `0x5A`.
- CANtap received it with no errors (TEC and REC 0) and ACKed it.
- SmallCore saw the ACK and halted, the program's acked exit; its post-ACK byte read `0x50`, ACK bit 0, against `0x51` with no node listening.
- The captured CTX matched `can_ref.py` bit for bit: SOF, identifier, RTR/IDE/r0, DLC, data, CRC-15 `0x0499`, the stuff bits, the CRC and ACK delimiters, the ACK slot and EOF, every edge on a bit boundary.

RX, slot 15 `can_rx_bytes`:

- CANtap transmitted `0x123 [5A]`.
- SmallCore received it through the transceiver; the engine's RX buffer read `12 30 2B 41 26 01`, the reference's destuffed stream exactly.
- CANtap's transmission succeeded first time, so the other physical node accepted SmallCore's ACK. The bus capture decoded as `0x123`, DLC 1, `0x5A`, CRC `0x0499` correct, ACK dominant.
- CANtap's bit time measured on the PYNQ was 8.0 µs, 125 kbit/s exactly.

Findings:

- The SmallCore RTL and its ROM programs needed no changes. Every failure on the way was in the harness, the wiring or the other node.
- The Nucleo-side wiring at first held the CAN controller's receive pin low, so it never saw an idle bus: it never transmitted and never received. The signature was transmissions that time out while the error counters never rise.
- CANtap's firmware ran the FDCAN from an 85 MHz clock while its bitrate table assumed 170 MHz, so every bitrate was half the one requested. Fixed in the CANtap repository, not here.
- The harness needs the FPGA-side buffering: VIO from the PC cannot service the 4-byte FIFOs while a protocol runs. The first attempt left CTX dominant mid-frame, the core stalled on PULL.
- The ROM CAN programs expect one data byte; a DLC 2 frame is outside their scope.
- The 125 kbit/s ceiling is a current program and timing limitation, not a core bug. `can_tx_crc` computes the CRC from the pad's readback on the second or third clock of each bit and samples the ACK early in the slot, so its own recessive must read back within one core clock and the other node's ACK must arrive by the slot's second clock. The transceiver loop measured about 0.33–0.46 µs dominant and 0.16 µs recessive, and the round trip to the other node and back about 0.8 µs: at 1 Mbit/s (125 ns clocks) the CRC came out wrong (`0x4C0D`), and by the simulated limits 250 kbit/s would miss the ACK (not tried on hardware). At 125 kbit/s (1 µs clocks) both fit. A program that samples later in the bit would lift it.

The full bring-up log, with every capture and the layer each finding belongs to, is `build/pynq_z2_can/bringup_log.md` on the bench machine (build/ is not committed); the findings above are its summary.

## The Zynq ARM as the host

The third wrapper, `smallcore_pynq_axi.v`, gives SmallCore a permanent host on the board itself: the Zynq's Cortex-A9. The ARM never makes a SmallCore bus transaction. It talks AXI4-Lite to a peripheral in the core's clock domain, and the same FPGA host engine as the VIO build makes every transaction at host.v's timing, so protocol timing stays in the FPGA and the core.

```
ARM (bare metal now, PYNQ Linux later) -> M_AXI_GP0 -> AXI3 to AXI4-Lite -> AXI clock converter
  -> smallcore_axi.v -> host_engine (can_host_engine.v) -> rtl/smallcore.v, unchanged -> smallcore_pads.v
```

```
smallcore_pynq_axi.v  the wrapper: the block design sc_ps, the MMCM core clock, the peripheral, SmallCore, the pads
smallcore_axi.v       the AXI4-Lite peripheral and the register map, the ARM ABI v1 (its header is the reference)
smallcore_pads.v      CTRL[2]: CAN on PMOD A (pin 1 CTX, pin 2 CRX) or the four GPIOs on PMOD B pins 1..4
can_host_engine.v     host_engine, the engine extended (CONTROL by value, raw transactions, a TX byte stream with a
                      completed-transaction count, an RX ring); can_host_engine wraps it with the VIO's old ports
ps7_pynq_z2.tcl       the PS7 settings of the PYNQ v3.0.1 base overlay (DDR, UART0 MIO 14..15, 50 MHz PS clock)
build_axi.tcl         the block design and bitstream, and the .xsa (with ps7_init.tcl and the .hwh); -tclargs CORE_DIV
pynq_z2_axi.xdc       pins: sysclk, LD0..3, PMOD A as the CAN build, PMOD B pins 1..4 pulled up
arm/                  bare-metal Cortex-A9: start.S, uart.c, smallcore.c/.h (the driver), test_host.c, can_bench.c,
                      test_ram.c, diag_tx.c; build.py (Arm GNU toolchain, no BSP, OCM); run_arm.tcl (xsdb over JTAG)
sim/                  tb_host_engine.v (run_engine_sim.py), tb_axi_host.v (run_axi_sim.py)
```

The only crossing between the PS's 100 MHz FCLK0 and the core clock is the Xilinx AXI clock converter; no AXI handshake reaches host_we or host_re. The peripheral is at `0x43C0_0000`. In outline: ID `0x53434F52`, VERSION, SCRATCH, CTRL (core reset, RX enable, pads), STATUS, COMMAND (RUN, RX clear, TX flush, TX_COMMITTED clear), SLOT (the CONTROL byte RUN writes), TX_DATA (stage a byte), TX_COUNT, RX_DATA (pop, with a valid bit), RX_COUNT, RAW (one SmallCore host transaction, read or write), CORE_STATUS (SmallCore's STATUS), TX_COMMITTED. The rules a driver relies on, all reported by the hardware rather than timed:

- RUN writes CONTROL ahead of any staged bytes. STATUS[6] RUN busy stays set until CONTROL is written and SmallCore's STATUS read again, so once it clears, CORE_STATUS describes the program RUN started and not the halt of the one before.
- TX_COMMITTED counts staged bytes whose TX_DATA transaction has completed: a TX FIFO push in a protocol program, a loader byte with CONTROL 0x20. Before RUN of a protocol program, wait for TX_COMMITTED ≥ min(n, 4) and, with n ≥ 4, CORE_STATUS tx_full: the prefill is the core's own.
- A RAM load is CONTROL 0x20, the words low byte first through TX_DATA, then TX_COMMITTED = 2 × words with STATUS idle, then CONTROL 0x10. Load mode lasts until the next CONTROL write, so bytes meant for the program wait until after the 0x10.

Build, simulate, run (Vivado 2023.2 for the build, the Arm GNU toolchain, xsdb from any recent Vivado; the board in JTAG boot mode):

```
vivado -mode batch -source fpga/pynq_z2/build_axi.tcl -tclargs 8
python fpga/pynq_z2/sim/run_sim.py
python fpga/pynq_z2/sim/run_engine_sim.py
python fpga/pynq_z2/sim/run_axi_sim.py
python fpga/pynq_z2/arm/build.py test_host smallcore.c --asm programs/spi/spi_duplex_msb.asm:spi_duplex_msb
xsdb fpga/pynq_z2/arm/run_arm.tcl <ps7_init.tcl from the .xsa> build/pynq_z2_axi/smallcore_pynq_axi_div8.bit build/pynq_z2_axi/arm/test_host.elf <result> 40 <tests> 0x1F <exception_seen>
```

`build.py` prints the `result` and `exception_seen` addresses; the program reports on the PROG/UART micro-USB's serial port at 115200 baud, and into `result`, which `run_arm.tcl` reads back over JTAG.

### ARM host validation

2026-10-18, PYNQ-Z2 in JTAG boot mode, bare-metal Cortex-A9 from OCM, CORE_DIV 8, the same bus and Candor node as above.

- Boundary: the ARM read ID and VERSION and wrote and read back SCRATCH, 8 patterns and a 1000-write sweep, through the protocol and clock converters.
- SmallCore: raw reads of STATUS (`0x05` at slot 0) and CONTROL, CONTROL by RUN and by raw write, read back.
- RAM loading: programs of 1 to 200 PUSH words loaded with CONTROL 0x20 / TX_DATA / 0x10 and run, the RX count equal to the word count every time; the 22-word `spi_duplex_msb` loaded, TX_COMMITTED 44, the TX FIFO never full.
- CAN RX, slot 15: Candor sent `0x123 [5A]` ten times; SmallCore received all ten, `12 30 2B 41 26 01` each, and Candor saw ten ACKs.
- CAN TX, slot 13: 60 frames, every one ACKed; Candor received `0x123 [5A]` with no CRC or other errors. Prefill before each RUN: TX_COMMITTED 4 and CORE_STATUS tx_full.
- The VIO build, rebuilt on the extended engine, still passes `run_sim.py`'s 40 cases with output identical to before the change, and on the board sent a frame matching the reference bit for bit, ACKed.

Findings:

- Vivado placed the 1 KiB TX staging FIFO in a block RAM, with the read pointer as the RAM's address register, enabled only when the pointer moved. A byte written into an empty FIFO, at the address being read, never reached the engine; it passed in simulation, where the read is combinational. On the board, CAN frames went out with a wrong CRC (the polynomial bytes are the first two staged) and RAM loads stored zeros. Raw TX_DATA writes, which bypass the FIFO, worked, which isolated it. The FIFO is now distributed RAM by attribute.
- Without the MMU, memory is strongly ordered and an unaligned access faults; GCC for the Cortex-A9 assumes it may make them. `build.py` compiles with `-mno-unaligned-access`, and `start.S` has a vector table that reports any exception on the UART instead of running into the startup code.
- The transceiver loop delay on the rewired bus measured 192 ns dominant, 144 ns recessive.

More CAN, the same evening, ARM-hosted (`arm/can_bench.c`), the Candor driven from CANtap's Lua scripting:

- ID sweep, 8 (ID, data) pairs chosen for bit stuffing (`0x000/00`, `0x7FF/FF`, `0x555/55`, `0x2AA/AA`, `0x7F0/0F`, `0x00F/F0`, `0x123/5A`, `0x5A3/A5`), 10 frames each: SmallCore TX 80/80 ACKed and received exact by the Candor; Candor TX 80/80 received by slot 15, decoded on the PC with `can_ref.py`, and 80/80 by slot 14 (`can_rx_crc`, CRC checked by SmallCore, residue 0, 0), its first hardware run.
- Soak: SmallCore TX 500 frames 20 ms apart, 500 ACKed and 500 received exact (and a 1478-frame run, all ACKed). Candor TX 400 frames: 397 received; the 3 others arrived while the single-frame receiver was being re-armed and the Candor does not retransmit.
- 250 kbit/s (CORE_DIV 4): on the rewired bus, loop delay 200 ns dominant, 144 ns recessive against a 500 ns core clock, TX bit-exact with the reference and ACKed (VIO build), RX exact (VIO and ARM), the ID sweep 80/80 ACKed and received, and a 400-frame slot 14 soak. The 125 kbit/s ceiling above was the earlier wiring's loop delay.

Finding: the RX programs hard-sync on the SOF and never resynchronise, sampling late in each bit. The Candor's FDCAN runs from the STM32's internal RC oscillator, about 2700 ppm off (CANtap's own drift estimate), which moves the sample point about 1 µs over a frame: in the soaks 1.3% (125k, slot 15) and 2.3% (250k, slot 14, flagged by SmallCore's CRC check) of frames had their last one or two CRC bits read as the recessive delimiter. A program limitation, not the core; a receiver that resynchronises on recessive-to-dominant edges, as CAN controllers do, would remove it.

Not yet done: the SPI loopback test needs a jumper from PMOD B pin 1 to pin 4 (without it MISO reads its pull-up, `0xFF`, as seen).

Settled: at the Candor's channel start the host had seen about 15 copies of a frame 2 ms apart, which looked like SmallCore missing ACKs. A cold connect showed otherwise. `can_tx_crc` pushes `{the last seven samples, ACK}` after every attempt and waits for the host's next frame bytes rather than retransmitting by itself, so the ARM bench sends one frame per 500 ms tick and logs each one's ACK. With the Candor's channel stopped, 30 ticks went unACKed; from its START every frame was ACKed on its only attempt, and the Candor received one frame per tick with none in the first 30 ms. The copies were a backlog the Candor had kept from an earlier session that left its channel started, delivered on reconnect: a CANtap issue, not SmallCore.

### Experiment: the TX CRC from the driven level, not the bus (2026-10-19)

At 1 Mbit/s (CORE_DIV 1, a 125 ns core clock) `can_tx_crc` sends frames with a wrong CRC: its `ACC_CRC 0` on the third clock of each bit reads the pad, the bus as the transceiver returns it, and the loop (192 ns dominant, 152 ns recessive) is longer than a clock. The question: does separating the bit as intended from the bit as observed remove that limit?

Setup, no change to the core, the ISA, the ROM or the wrappers:

- A jumper on the board from PMOD A pin 1 (CTX) to PMOD A pin 3, which CAN mode already reads as gpio_in 1.
- `experiments/can_stress/gen.py` takes `crc_pin`: `tx(crc_pin=0)`, the default, is `can_tx_crc.asm` word for word; `tx(crc_pin=1)` is `experiments/can_stress/can_tx_crc_pin1.asm`, the same 152 words but for the 10 `ACC_CRC` words. Every `SHIFT_IN`, the stuffing's run test and the ACK, still reads the bus on pin 0.
- The program runs from RAM: `arm/can_bench.c`'s `tx_ram` (built with `--asm experiments/can_stress/can_tx_crc_pin1.asm:can_tx_ram`) loads it before each frame, parks on slot 0, prefills the frame and runs CONTROL 0x10; `can_host.tcl`'s `can_tx_ram` does the same over the VIO's manual port for the ILA captures.
- Model: `Bus(jumper=, delay=)` in `tests/model/test_can.py`; xsim: `tb_axi_host.v`'s transceiver `delay` and the jumper as a wire, mode 6 (CAN TX from RAM), `run_axi_sim.py --limits`.

Hardware, 8 (ID, data) pairs chosen for stuffing × 10 frames, ARM-hosted, each cell Candor received exact · Candor bus errors · SmallCore's ACK exits:

| rate | slot 13 from ROM | slot 13 from RAM (control) | `crc_pin` 1 from RAM |
|---|---|---|---|
| 125 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 250 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 500 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 1 Mbit/s | 0 · CRC errors · 0/80 | 0 · CRC errors · 0/80 | **80/80 · none · 0/80** |

At 1 Mbit/s, with the CRC accumulated from the locally driven TX level, the Candor receives 80/80 frames exactly with no CAN bus errors. ILA capture of one frame (0x123, 0x5A; `can_decode.py`): CTX matches `can_ref.py` bit for bit, CRC-15 `0x0499`, stuffing correct, every edge on a bit boundary; the bus (CRX) carries the same correct frame and the Candor's ACK. SmallCore still misses the ACK: it becomes visible on the synchronized input (`crx_s`) on clock 5 of the ACK slot, and the program samples clock 4 (`NOP [2]`, `SHIFT_IN 0`). So the CRC limitation is eliminated; successful 1 Mbit/s transmission by SmallCore is not yet shown.

Simulation agrees. Model: 6A tolerates a readback delay of 1 clock (from 2 the identifier and data arrive right and the CRC wrong); `crc_pin` 1 tolerates 2, and at 3 the run test's bus sample (clock 4) breaks the stuffing. RTL (`run_axi_sim.py --limits`, one more flop on CRX): `crc_pin` 1 keeps the frame exact through a 1-clock loop where slot 13's CRC already fails, both break at 2, and both miss an ACK that arrives a clock or more late.

A pitfall found on the way: running the RAM program first and staging the frame after (as the RAM load's own order invites) lets the program PULL mid-frame before its byte is in; from 500 kbit/s that stretched a bit and broke every frame, for slot 13's program in RAM too. Park on slot 0 and prefill, as `can_bench.c` now does.

#### The ACK sample clock (2026-10-19)

`gen.py`'s `ack_sample` moves the ACK slot's `SHIFT_IN` to a later clock and changes nothing else: `ack_sample=4`, the default, is the existing program word for word; 5 and 6 (`can_tx_crc_pin1_ack5.asm`, `_ack6.asm`, both with `crc_pin` 1) differ only in the slot's `NOP` and `SHIFT_IN` delays, so the data bits, stuffing and CRC keep their schedule. ACK sensing stays on pin 0.

Hardware, same matrix and bench (ARM `tx_ram`), Candor received exact · Candor bus errors · SmallCore's ACK exits:

| rate | ACK on clock 4 (above) | ACK on clock 5 | ACK on clock 6 |
|---|---|---|---|
| 125 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 250 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 500 kbit/s | 80/80 · none · 80/80 | 80/80 · none · 80/80 | 80/80 · none · 80/80 |
| 1 Mbit/s | 80/80 · none · 0/80 | 80/80 · none · 0/80 | **80/80 · none · 80/80** |

1 Mbit/s ILA (0x123, 0x5A, VIO `can_tx_ram`, one frame each program): CTX matches `can_ref.py` for all three, CRC-15 `0x0499`; the Candor's ACK is on `crx_s` from clock 5 of the ACK slot to clock 3 of the delimiter; clock 4 and clock 5 miss it (post-ACK byte 0x33), clock 6 takes it (0x32). So clock 6 is one clock after the ACK first shows on `crx_s`, and the program's sample clock 5 already reads a clock too early: the ACK arrives at the SHIFT_IN later than the ILA's view of `crx_s` by about a clock.

xsim (`run_axi_sim.py --limits`, the other node's ACK lag into the slot 0 to 8 clocks): sample clock 4 takes the ACK only on time (lag 0) through a 0-clock loop and never through a 1-clock loop; clock 5 tolerates lag + loop of 1 clock; clock 6, 2 clocks. Each later sample clock buys one clock of ACK delay.

So with the CRC from the driven level and the ACK sampled on clock 6, SmallCore sends 1 Mbit/s frames that the Candor receives exactly and acknowledges, and SmallCore takes the ACK exit, on this bench (one transceiver loop of 192/152 ns, one receiver, a jumper). Margin at 1 Mbit/s is one clock, and the jumper and RAM program are an experiment, not a change to the core, ISA, ROM or wrappers.
