# Instruction set and core

A mini PIO-style CPU simulator. 16-bit instructions with a per-instruction delay, four output pins `gpio[3:0]`, each push-pull or open-drain, four input pins `gpio_in[3:0]`, an 8-bit output shift register fed by a TX FIFO, an 8-bit input shift register drained into an RX FIFO, a wait on an input level, a skip on a bit of the input shift register or on a run of its newest samples, a counted repeat of a run of words, a sixteen-bit accumulator, a second stream register with optional LFSR feedback, and two pieces of configuration, `shift_dir` and `open_drain`. Eighteen mnemonics in eight opcodes. The encoding is in `isa.yaml`.

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
| `SKIP_RUN n, level [d]`, `SKIP_NORUN n, level [d]` | steps over the next word if the newest n samples in the input shift register are all `level`, or not all: n 1..8 |
| `ACC_IN pin [d]` | acc <- (acc << 1) \| gpio_in[pin]: the accumulator as a plain sixteen-bit stream register |
| `ACC_CRC pin [d]` | the same shift with LFSR feedback: f = acc[15] ^ gpio_in[pin], acc <- (acc << 1) ^ (f ? poly : 0), a CRC of any width to 16 |
| `ACC_OUT pin [d]` | gpio[pin] <- acc[15], then shift left: a CRC out MSB first |
| `ACC_PUSH [d]` | RX FIFO <- acc[7:0], then acc >> 8; stalls while the FIFO is full |
| `ACC_LOAD [d]` | poly <- {output shift register, poly[15:8]}: a polynomial byte from the host, low first |
| `JMP label [d]` | continue at label |
| `REPEAT count, label` | back to label until the words from label to here have run count times, 1..32; one cycle, no `[d]`: bits 12:8 hold the count |
| `CONFIG field, value [d]` | config[field] <- value: `shift_dir` 0 (reset) or 1, LSB or MSB first for both shift registers; `open_drain01` and `open_drain23`, a 2-bit mask for pins 1:0 or 3:2, 1 = open-drain |

`[d]` holds for d extra cycles. Every instruction but `JMP` and `REPEAT` can take a GPIO side effect, `pin, value` after its own operands, that drives one more pin on the same edge as the operation: `SHIFT_OUT 1, 0` puts the next bit on MOSI and drops the clock, `SHIFT_IN 3, 1, 1` raises the clock and samples MISO, `PULL 2, 0` drops CS the moment a byte arrives, `PUSH 2, 1` raises it as the received byte leaves, and a WAIT's side effect lands on the cycle the level arrives. `SET` is the side effect on its own. The FIFOs are fed and drained from outside the core: by the test bench, the CLI, or the host register bus of `rtl/smallcore.v`, the chip, which also holds every program in a ROM (see Host interface).

