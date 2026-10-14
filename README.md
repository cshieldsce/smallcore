# smallcore

A small programmable protocol engine in Verilog, in the spirit of the RP2040's PIO. A 16-bit core with four output pins, four input pins and two FIFOs runs short assembly programs that bit-bang UART, SPI, I2C, SWD and Classical CAN.

**Status: verified in simulation and run through an open ASIC flow. Not yet tested on hardware.**

## Motivation

This started from Jane Street's [protocol emulator ASIC competition](https://blog.janestreet.com/protocol-emulator-asic-competition/). Rather than ask how to build a machine for any protocol, I started small: what is the minimum hardware communication needs? I mapped each protocol, up to CAN, to the least hardware that could run it, on paper, then built it in this order:

1. A Python golden model and assembler (`model/cpu.py`), built with AI assistance.
2. Protocol programs I wrote in assembly and tested against that model.
3. RTL I wrote from the model. The same programs and the model then drive the RTL benches, and they pass.

I also wanted to see how to use AI effectively without trusting it blindly. The model is the part AI helped build, so it is never taken on faith: everything it claims has to survive programs I wrote and an RTL implementation I wrote myself.

## What runs on it

| Protocol | ROM slots |
|---|---|
| UART TX (three variants), RX | 1-4 |
| SPI TX and full duplex, LSB or MSB first | 5-8 |
| I2C master write (plain, clock stretching, address + data) | 9-11 |
| SWD read | 12 |
| Classical CAN (not CAN FD): TX with CRC, RX with CRC, RX bytes | 13-15 |

Further CAN programs (arbitration, ACK, stuffing) are in `programs/can/` and tested at the pins but not in the ROM. 10BASE-T Ethernet is an experiment only.

![Block diagram: host registers, ROM and RAM, fetch and execute, TX and RX FIFOs with shift registers, and the GPIO pins](docs/sketches/block-diagram.png)

*Hand-drawn block diagram. More sketches, from the first box to this one, are in [docs/design-sketches.md](docs/design-sketches.md).*
## Verification

```bash
pip install -r requirements.txt   # also needs Verilator on PATH
make test         # rom-check + model tests + RTL tests, about 8 minutes
make test-model   # tests/model: 3,893 pytest cases against the Python model
make test-rtl     # tests/rtl: 11 cocotb modules against rtl/ under Verilator
```

The RTL benches step the model and the RTL cycle by cycle for the core, and check pins and clock counts against the model for every program at the top level. `make rom-check` fails if `rtl/rom.v` differs from what `tools/gen_rom.py` builds from `programs/manifest.txt`.

## Status

- Simulation: all tests pass.
- ASIC flow: through Tiny Tapeout IHP CMOS5L at 6x4 tiles, zero DRC, antenna and LVS violations on each recorded row. Numbers in [docs/physical-results.md](docs/physical-results.md).
- **Not done:** no FPGA board run, no silicon, no test against real devices or a CAN bus. The chip-level bench drives the UART and SPI slots through the host bus. I2C, SWD and CAN are verified at `top.v`, not yet from the ROM through the host bus.
- Limits: the CAN receiver cannot hold raw history, data and CRC at once, and its ACK cannot depend on the CRC. No ROM slot is free.

## Layout

`isa/` instruction set · `model/` golden model and assembler · `rtl/` Verilog · `programs/` assembly and ROM manifest · `tests/` model and RTL tests · `tools/` ROM generator and helpers · `experiments/` candidates that shaped the ISA · `asic/janestreet/` Tiny Tapeout packaging · `fpga/pynq_z2/` simulated only · `docs/` below

## Docs

[Design sketches](docs/design-sketches.md) · [Instruction set](docs/isa.md) · [Host interface](docs/host-interface.md) · [Design history](docs/design-history.md) · [Commands](docs/commands.md) · [Diagrams](docs/diagrams/README.md) · [Physical results](docs/physical-results.md) · [CAN](docs/can-combined.md)
