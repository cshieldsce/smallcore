# Design sketches

Hand-drawn notes from before the RTL existed. They are early: the opcode list below is the first five groups, not the final instruction set (see [isa.md](isa.md) for the 18 mnemonics).

## Start small

The starting point was one box: a host byte goes in, a program is loaded, GPIO comes out.

![A box labelled tiny programmable core, with host byte in, program in and GPIO out](sketches/start-small.png)

Then three questions, each answered with the least hardware that would do: something to hold a program, something to say which instruction runs next, and something to turn bytes into bits and hold them.

![Three small diagrams: instruction memory, a program counter feeding instruction memory, and a host byte into a shift register out to GPIO](sketches/three-questions.png)

## First datapath

Those three parts joined up, with a TX and an RX FIFO between the host and the pins.

![PC feeding instruction memory and decode, with TX and RX FIFOs each paired with a shift register to GPIO and the host reading and writing the FIFOs](sketches/first-datapath.png)

## Control unit and first opcodes

![Control unit with delay, opcode, PC, TX empty, RX full, GPIO and input shift register as inputs, and shift in, shift out, GPIO, push and pull as outputs](sketches/control-unit.png)

![The first opcodes: SET, SHIFT IN/OUT, PUSH/PULL, JMP, WAIT](sketches/opcodes.png)

## Block diagram

The datapath once it had program memory (ROM and a 256 x 16 RAM), four host registers, and the stall points: PULL waits while the TX FIFO is empty, PUSH waits while the RX FIFO is full, WAIT holds until the pin is at the level.

![Block diagram: ROM and RAM feed fetch, execute drives GPIO out, TX FIFO feeds the output shift register, GPIO in feeds the input shift register and the RX FIFO, and the host has four registers](sketches/block-diagram.png)
