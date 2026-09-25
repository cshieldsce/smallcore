# core

A mini PIO-style CPU simulator: a 16-bit ISA with `SET` / `SHIFT_OUT` / `PULL` / `JMP` / `CONFIG_SHIFT` / `SHIFT_IN` and per-instruction delays, driving four output pins `gpio[3:0]` and sampling four input pins `gpio_in[3:0]`. `SET pin, value` drives one pin and leaves the others alone; `SHIFT_OUT` always drives `gpio[0]` from an 8-bit output shift register, and `SHIFT_OUT pin, value` also drives one more pin on the same edge (a GPIO side effect, which is what lets SPI drop the clock as the next bit lands on MOSI). The output shift register is filled by `PULL` from a TX FIFO fed from outside the core, so one program can transmit any data. `PULL` blocks while the FIFO is empty, and `JMP` (absolute 8-bit address, labels resolved by the assembler) lets a program loop back to its `PULL` and stream bytes for as long as the FIFO is fed. Which end of the shift registers is the wire is not part of `SHIFT_OUT` but one bit of persistent configuration, `shift_dir`: it resets to LSB first (UART) and `CONFIG_SHIFT 1` switches to MSB first (SPI) until the next `CONFIG_SHIFT`, so a program states its bit order once, not once per bit. The receive side mirrors the transmit side: `SHIFT_IN pin` samples `gpio_in[pin]` into an 8-bit input shift register at the end opposite the wire, obeying the same `shift_dir`, so eight samples rebuild the byte in normal order whichever way it came; `SHIFT_IN pin, out_pin, value` also drives a pin on the sampling edge, which is what lets SPI raise the clock and read MISO in one instruction. The sample is the level the pin holds as that cycle executes, before anything the same edge drives. `SHIFT_OUT` and `SHIFT_IN` share one opcode, `SHIFT`, told apart by an in/out bit in the operand: they already shared `shift_dir`, the delay and the side effect, so the mnemonics stay and opcode `101` is free again. There is no `PUSH` or RX FIFO yet: the test bench reads the register.

```
isa.yaml      instruction set: encoding, opcodes, operand ranges
programs/     assembly programs (.asm)
sim/          simulator (cpu.py)
tests/        pytest test benches
docs/         Mermaid diagrams (.mmd) and rendered .svg, see Docs below
tools/        wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
build/        generated: test waveforms, caches (safe to delete)
```

## Commands

```
python -m pip install -r requirements.txt
python -m pytest -v              # run tests, writes build/waves/<test bench>/<test>.svg
python sim/cpu.py                # run programs/uart_tx_0x55.asm, print listing + one trace per gpio pin
python sim/cpu.py programs/uart_tx_pull.asm 0xA3    # send a byte from the TX FIFO via PULL + SHIFT_OUT
python sim/cpu.py programs/uart_tx_loop.asm 0x55 0xA3   # stream bytes: PULL / frame / JMP loop until the FIFO is empty
python sim/cpu.py programs/spi_tx_lsb.asm 0xA3      # SPI mode 0 TX, LSB first: MOSI on gpio 0, SCLK on gpio 1, CS on gpio 2, 2 instructions per bit
python sim/cpu.py programs/spi_tx_msb.asm 0xA3      # the same transfer MSB first: one CONFIG_SHIFT 1 is the only difference
python sim/cpu.py programs/spi_duplex_msb.asm 0xA3  # full duplex: the TX program with SHIFT_IN 3, 1, 1 raising SCLK and sampling MISO on gpio_in 3 (the CLI holds inputs at 0; the SPI test bench drives a slave)
python tools/render_docs.py      # re-render docs/*.svg (needs mermaid-cli)
```

## Design pressures

What the protocols have asked of the core so far, in the order they came up. Solved items say how; open ones stay open until a program actually needs them.

| pressure | from | status |
|---|---|---|
| more than one output pin | SPI | done: `gpio[3:0]`, `SET pin, value` |
| shift and drive a second pin on the same edge | SPI, 3 instructions per bit | done: `SHIFT_OUT pin, value`, SPI is 2 instructions and 8 cycles per bit |
| selectable shift direction (MSB first) | SPI | done: `shift_dir` configuration bit set by `CONFIG_SHIFT`, `SHIFT_OUT` sends bit 7 and shifts left when it is 1 |
| read a pin on the same edge that raises the clock (MISO) | SPI full duplex | done: `gpio_in[3:0]`, an input shift register, `SHIFT_IN pin, out_pin, value`; obeys `shift_dir`; RX costs no instructions and no cycles on top of TX |
| get the received byte out of the core | SPI full duplex | open, next: `PUSH` into an RX FIFO, the mirror of `PULL` |
| six of eight opcodes used before `PUSH` | the ISA itself | in progress: `SHIFT_OUT` + `SHIFT_IN` are one `SHIFT` opcode with an in/out bit; `CONFIG`, a universal GPIO side effect and a `PULL`/`PUSH` bit are next |
| compact repetition / bit count | SPI, 16 unrolled words per byte | open, later |
| per-pin reset or idle level | SPI, one `SET` to take SCLK low | open, maybe: not hurting enough yet |
| configurable shift-output pin | SPI | open, not yet justified: fixed `gpio[0]` has not caused a failure |

The shift direction was the first thing that fit none of the existing state. The core now has three kinds: instruction state (`pc`, the delay counter), stream state (`shift_reg`, `in_shift_reg`, the TX FIFO) and protocol configuration (`shift_dir`, so far alone, and now shared by both shift registers). Shift pin, input pin and pin directions may join the third kind later; whether it becomes a configuration register is left open until something forces it.

## Docs

From the big picture down to what the Verilog will look like:

| diagram | shows |
|---|---|
| `docs/overview.svg` | the big picture: program and bytes go in, UART or SPI comes out on the gpio pins, and how a byte reaches them |
| `docs/isa_encoding.svg` | the 16-bit instruction word: opcode / delay / operand fields for each instruction |
| `docs/isa_execute.svg` | what each instruction does and how many cycles it takes, including the PULL stall |
| `docs/core.svg` | datapath at register level: every register with its reset value and enables, named as in the Verilog |
| `docs/control.svg` | the control block: its inputs, the equations it computes, the counter, and the enables it drives |
| `docs/states.svg` | the same control block as per-cycle states: Issue, Hold, Stall, Halt |

Diagrams only show hardware that exists in `sim/cpu.py` and passes the tests.
