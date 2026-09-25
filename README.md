# core

A mini PIO-style CPU simulator. 16-bit instructions with a per-instruction delay, four output pins `gpio[3:0]`, each push-pull or open-drain, four input pins `gpio_in[3:0]`, an 8-bit output shift register fed by a TX FIFO, an 8-bit input shift register drained into an RX FIFO, a wait on an input level, a skip on a bit of the input shift register, and two pieces of configuration, `shift_dir` and `open_drain`. Ten mnemonics in seven opcodes, one free. The encoding is in `isa.yaml`.

| instruction | does |
|---|---|
| `NOP [d]` | nothing |
| `SET pin, value [d]` | gpio[pin] <- value |
| `SHIFT_OUT [d]` | gpio[0] <- next bit of the output shift register, then shift |
| `SHIFT_IN pin [d]` | sample gpio_in[pin] into the input shift register, then shift |
| `PULL [d]` | output shift register <- next TX FIFO byte; stalls while the FIFO is empty |
| `PUSH [d]` | RX FIFO <- input shift register; stalls while the FIFO is full |
| `WAIT pin, level [d]` | stalls while gpio_in[pin] != level, a level not an edge |
| `SKIP bit, level [d]` | steps over the next word if in_shift_reg[bit] == level: pc <- pc + 2 |
| `JMP label [d]` | continue at label |
| `CONFIG field, value [d]` | config[field] <- value: `shift_dir` 0 (reset) or 1, LSB or MSB first for both shift registers; `open_drain01` and `open_drain23`, a 2-bit mask for pins 1:0 or 3:2, 1 = open-drain |

`[d]` holds for d extra cycles. Every instruction but `JMP` can take a GPIO side effect, `pin, value` after its own operands, that drives one more pin on the same edge as the operation: `SHIFT_OUT 1, 0` puts the next bit on MOSI and drops the clock, `SHIFT_IN 3, 1, 1` raises the clock and samples MISO, `PULL 2, 0` drops CS the moment a byte arrives, `PUSH 2, 1` raises it as the received byte leaves, and a WAIT's side effect lands on the cycle the level arrives. `SET` is the side effect on its own. The FIFOs are fed and drained from outside the core, by the test bench or the CLI.

```
isa.yaml      instruction set: encoding, opcodes, operand ranges
programs/     assembly programs (.asm)
sim/          simulator and assembler (cpu.py)
tests/        pytest test benches
docs/         Mermaid diagrams (.mmd) and rendered .svg, see Docs below
tools/        wavetrace.py (waveform helper), render_docs.py (docs/*.mmd -> .svg)
build/        generated: test waveforms, caches (safe to delete)
```

## Commands

```
python -m pip install -r requirements.txt
python -m pytest -v                                 # writes build/waves/<test bench>/<test>.svg
python sim/cpu.py                                   # runs programs/uart_tx_0x55.asm: listing + one trace per pin
python sim/cpu.py programs/uart_tx_pull.asm 0xA3    # one byte from the TX FIFO
python sim/cpu.py programs/uart_tx_loop.asm 0x55 0xA3   # streams the FIFO, then stalls on PULL
python sim/cpu.py programs/spi_tx_lsb.asm 0xA3      # SPI mode 0: MOSI, SCLK, CS on gpio 0, 1, 2
python sim/cpu.py programs/spi_tx_msb.asm 0xA3      # same words except CONFIG shift_dir, 1
python sim/cpu.py programs/spi_duplex_msb.asm 0xA3  # also samples MISO on gpio_in 3 and PUSHes the byte (the CLI holds inputs at 0)
python -m pytest tests/test_uart_rx.py -v           # UART RX: uart_rx.asm fed by uart_tx_loop.asm over a wire, waves in build/waves/uart_rx/
python -m pytest tests/test_i2c.py -v               # I2C master write on a bus model with a slave: one byte, clock stretching, address + data
python tools/render_docs.py                         # docs/*.mmd -> .svg (needs mermaid-cli)
```

## Design pressures

What the protocols have asked of the core, in order. Open items stay open until a program needs them.

| pressure | from | status |
|---|---|---|
| more than one output pin | SPI | `gpio[3:0]`, `SET pin, value` |
| shift and drive a second pin on one edge | SPI | the side effect: 2 instructions, 8 cycles per bit |
| MSB first | SPI | `shift_dir`, `CONFIG shift_dir, 1` |
| sample a pin on the edge that raises the clock | SPI duplex | `gpio_in[3:0]`, `SHIFT_IN pin, out_pin, value`; RX costs no instructions or cycles |
| get the received byte out | SPI duplex | `PUSH` into an RX FIFO; `PUSH 2, 1` also ends the frame |
| six of eight opcodes used | the ISA | one `SHIFT` opcode with an in bit, one `FIFO` opcode with a push bit, generic `CONFIG`, the side effect on every opcode, `SET` = `NOP` + side effect |
| wait for an input level: the start bit | UART RX | `WAIT pin, level`: the stall PULL and PUSH already had, with a pin level as its third condition; `uart_rx.asm` is 11 words, `WAIT 0, 0 [11]` then eight mid-bit `SHIFT_IN`s |
| let go of a line: a third output state | I2C | `open_drain[3:0]`, one mode bit per pin: `gpio_oe[k] = !(open_drain[k] & gpio[k])`, an open-drain pin drives its 0 and lets go on a 1; the same words see the ACK and follow the stretch. `CONFIG open_drain01, 3` sets both I2C pins in one word: two 2-bit fields cover the four pins with CONFIG's shape unchanged, field 3 stays free |
| wait for the clock to really rise | I2C clock stretching | `SET 1, 1` then `WAIT 1, 1 [2]`: the WAIT as built, one more word per clock |
| act on the ACK: STOP after a NACK | I2C address + data | `SKIP bit, level`, pc + 2 when a bit of the input shift register holds the level: `SKIP 0, 0` then `JMP stop` after the ACK clock, from the register since SDA has let go by then. A conditional JMP on the last sample was one word shorter and could not pick the bit, the polarity or the word it guards; JMP keeps its 8-bit target |
| compact repetition / bit count | SPI, 16 words per byte; I2C, 3 per bit | open |
| per-pin idle level | SPI, one `SET` for SCLK | open, not hurting yet |
| configurable shift-output pin | SPI | open, fixed `gpio[0]` has not failed |

Three kinds of state: instruction (`pc`, the delay counter), stream (the shift registers and FIFOs) and configuration (`shift_dir`, `open_drain`), each a `CONFIG` field. A shift pin or input pin would join the third kind as the last field.

## Docs

From the big picture down to what the Verilog will look like:

| diagram | shows |
|---|---|
| `docs/overview.svg` | program and bytes in, UART or SPI out, how a byte reaches the pins |
| `docs/isa_encoding.svg` | the 16-bit word: opcode / delay / side effect / own operands per instruction |
| `docs/isa_execute.svg` | what each instruction does, cycles, the PULL, PUSH and WAIT stalls |
| `docs/core.svg` | datapath at register level, named as in the Verilog |
| `docs/control.svg` | the control block: inputs, equations, counter, enables |
| `docs/states.svg` | the same block as per-cycle states: Issue, Hold, Stall, Halt |

Diagrams show only hardware that exists in `sim/cpu.py` and passes the tests.
