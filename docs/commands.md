# Commands


```
python -m pip install -r requirements.txt           # plus Verilator 5.036+ on the PATH for the RTL
python -m pytest -v                                 # writes build/waves/<test bench>/<test>.svg
python model/cpu.py                                   # runs programs/uart/uart_tx_0x55.asm: listing + one trace per pin
python model/cpu.py programs/uart/uart_tx_pull.asm 0xA3    # one byte from the TX FIFO
python model/cpu.py programs/uart/uart_tx_loop.asm 0x55 0xA3   # streams the FIFO, then stalls on PULL
python model/cpu.py programs/spi/spi_tx_lsb.asm 0xA3      # SPI mode 0: MOSI, SCLK, CS on gpio 0, 1, 2
python model/cpu.py programs/spi/spi_tx_msb.asm 0xA3      # same words except CONFIG shift_dir, 1
python model/cpu.py programs/spi/spi_duplex_msb.asm 0xA3  # also samples MISO on gpio_in 3 and PUSHes the byte (the CLI holds inputs at 0)
python -m pytest tests/model/test_uart_rx.py -v           # UART RX: uart_rx.asm fed by uart_tx_loop.asm over a wire, waves in build/waves/uart_rx/
python -m pytest tests/model/test_i2c.py -v               # I2C master write on a bus model with a slave: one byte, clock stretching, address + data
python model/cpu.py programs/swd/swd_write.asm 0xA9      # SWD write: request, turnaround, ACK, turnaround back, branch on the ACK, on OK four data bytes and a parity byte; SWDIO on gpio 0, SWCLK on gpio 1 (the CLI holds inputs at 0: no ACK, the program exits)
python model/cpu.py programs/swd/swd_read.asm 0x8D       # SWD read: on OK 32 data bits and the parity follow, six bytes to the host (the CLI holds inputs at 0: no ACK, the program exits)
python -m pytest tests/model/test_swd.py -v               # SWD: a target on the wire decodes every request the host can make, answers OK, WAIT or FAULT, sends a word
python model/cpu.py programs/can/can_tx.asm 0x5A 0x30      # CAN stage 1: the SOF and identifier 0x5A3 as two host bytes, 8 cycles a bit on gpio 0, the bus (the CLI holds inputs at 0: the sampled byte reads 0)
python model/cpu.py programs/can/can_tx_arb.asm 0x5A 0x30  # CAN stage 2: the same frame under arbitration, TXD on gpio 0 read back on gpio_in 0, the bus on gpio_in 1 (the CLI holds inputs at 0: TXD reads back dominant, nothing is ever lost, the frame goes out whole)
python model/cpu.py programs/can/can_tx_ack.asm 0x5A 0x30  # CAN stage 3: the frame, then the ACK slot let go and sampled, the decision in the delimiter (the CLI holds inputs at 0: acked, one byte, the halt)
python model/cpu.py programs/can/can_tx_stuff.asm 0x7F 0xF0 # CAN stage 4: 0x7FF stuffed, 16 cycles a bit, the decision tree needing seven after the sample (the CLI holds inputs at 0: every sample dominant, so a recessive stuff bit follows every bit from ID[7] on, 20 bits)
python model/cpu.py programs/can/can_tx_frame.asm 0x40 0xD1 0x81 0x5A 0x7D 0xAE  # CAN stage 5A: a whole data frame, 0x5A3 with one byte 0x5A and the CRC the host computed, 16 cycles a bit, the six bytes cut where the program's PULLs fall (the CLI holds inputs at 0: every sample dominant, so a recessive stuff bit follows every five bits, and the ACK slot reads acked)
python -m pytest tests/model/test_can.py -v               # CAN: a wired-AND bus with an ideal receiver and a competing transmitter; the SOF and the identifier held 8 cycles a bit, the sample point probed with a one-cycle glitch, a host late mid-frame, arbitration won and lost on every recessive bit, the ACK slot pulled dominant by the receiver or not, the frame again after no ACK, stuff bits after every run of five and a receiver that drops them; a whole data frame with the host's CRC through a 4-deep FIFO, every PULL and PUSH inside it stalled in turn
python model/cpu.py experiments/crc/crc4_lfsr.asm 0x5A 0x3A 0x00 0x5A  # CRC-4 on the current ISA: the widest CRC the core can compute, four bytes out on pin 0 and back, the feedback bit on pin 1 (the CLI holds inputs at 0, so nothing comes back: the byte reads 0; tests/model/test_crc.py wires the pads back)
python model/cpu.py programs/can/can_rx_destuff.asm       # CAN RX3 to RX5: the stuffing tree on the receive side at 8 cycles a bit, the stuff bit dropped, the destuffed stream on pins 2 and 3, the ACK slot pulled (the CLI holds inputs at 0: the SOF is seen at once and every sample is dominant, a stuff bit after every five)
python -m pytest tests/model/test_can_rx.py -v            # CAN RX on the current ISA, no candidate: the SOF by WAIT and 48 raw bits; the stuff test in a body at 8 clocks a bit, the stream on the pins, the ACK found; the stream through the FIFO a bit a byte at 9 clocks; bytes in the core counted at 1629 words for the header and refused
python -m pytest tests/model/test_crc.py -v               # CRC-15 on the current ISA, the three baselines: the oracle and the Fibonacci form, the census of what every word writes and reads, CRC-4 against the oracle, the CRC as data in the frame
python -m pytest tests/model/test_can_candidates.py -v    # the CAN candidates (experiments/can/) spliced into the arbitration and stuffing programs against the baselines, the bus cycle for cycle and bit for bit
python -m pytest tests/model/test_repeat.py -v            # REPEAT on the model: count 1..32, one- and 255-word bodies, stalls in the body, restart every cycle, the assembler's rules, every program with REPEAT against its canonical one
python -m pytest tests/model/test_repeat_candidates.py -v # the repeat candidates (experiments/repeat/) spliced into the SWD programs against the baseline, cycle for cycle
python experiments/repeat/suite.py                  # the existing model suite run on each candidate's model: what each one disturbs
python tools/render_docs.py                         # docs/*.mmd -> .svg (needs mermaid-cli)
make lint                                           # verilator --lint-only -Wall -Wno-fatal rtl/core.v
make test-rtl                                       # python -m pytest tests/rtl: Verilator builds core.v and top.v into build/rtl/, cocotb runs tests/rtl/*_tb.py
python -m pytest tests/rtl/test_smallcore.py -v     # the chip: host bus semantics, spi_duplex_msb from the ROM through the bus with a slave on the pads, the loopback
python -m pytest tests/rtl/test_rom.py -v           # rom.v word for word against the assembler
python -m pytest tests/rtl/test_pynq.py -v          # fpga/pynq_z2/ wrapper: buttons, debounce, LEDs, the PMOD jumper modelled in the bench
make rom                                            # programs/manifest.txt + the assembler -> rtl/rom.v; rom-check fails if it is stale (make test runs it)
python -m pytest tests/rtl/test_top_adversarial.py -v  # top.v under a hostile host: stalls held, delays one-shot, metamorphic pairs, seeded traffic in lockstep with the model
WAVES=1 make test-rtl                               # same, plus build/rtl/dump.vcd (gtkwave build/rtl/dump.vcd)
make test                                           # tests/ then tests/rtl/
```

