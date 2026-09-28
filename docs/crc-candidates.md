# CRC state candidates

**Outcome (2026-09-28): the accumulator adopted** ("Decided", below). W32
and Pin16 rejected, Lanes subsumed, every candidate program kept. First
measured with nothing merged, as follows.
The CRC baselines (`docs/crc-baselines.md`) left one wall, the width of
the state: `in_shift_reg` is the eight bits a program both writes and
reads, and CRC-15 wants fifteen, thirty in the form the core can execute.
RX left the same wall from the other side: the raw history the run test
reads and the destuffed data the host wants cannot share the one register.
So this round compares state architectures, not CRC opcodes, and asks one
question: what is the smallest generic state capability that explains both
failures?

Method as for REPEAT and CAN. Each candidate is `isa.yaml` plus its words
and a model that runs them (`experiments/crc/candidates.py`, built on the
CAN round's `Candidate`, so the step, REPEAT and the run test are the
model's). The programs are written by `experiments/crc/gen.py`. Each is held
to the oracle: four host bytes out on pin 0 MSB first and back through the
pad, and the CRC of the 32 bits out on pin 1 MSB first, on the 36 vectors
and 200 random streams. The receivers are held to the destuffed stream at
eight clocks a bit on the RX bench's six frames. Every candidate is checked
to take only words the ISA rejects today, with every program in `programs/`
assembling to the same words. Its semantics are pinned on every corner, and
a mutation of each model and of one program is caught
(`tests/test_crc_candidates.py`, 278 tests). Nothing in `isa.yaml`,
`sim/cpu.py` or the RTL changes.

## The candidates

**W16, W32: the existing register, wider.** The sample that leaves
`in_shift_reg`'s wire end goes into a second stage, 8 or 24 bits more, in
the same direction. `SKIP index, level` reaches ages 8 and up through the
bits its shape rejects. `in_shift_reg`, PUSH and the run test are as they
were: ages 0 to 7 are the register, the eighth newest sample is at 8.

**Pin8: the input without a slot.** `SKIP_PIN pin, level` steps over the
next word if the pad held `level` as the word issued, the way SHIFT_IN
samples. The input becomes a condition and never enters the register.

**Pin16: both.** W16 with SKIP_PIN: a sixteen-bit window the input does
not enter, the fifteen CRC-15 wants.

**Lanes: a second independent stream register.** `lane`, eight bits.
`SHIFT_IN1 pin` fills it alone, `SHIFT_IN01 pin` puts one sample into both
registers, `SKIP1 bit, level` reads it, `PUSH1` hands it to the host. The
run test reads lane 0.

**Acc: a generic LFSR accumulator.** A 16-bit `acc` and a 16-bit `poly`.
`ACC_IN pin`: f = acc[15] ^ the pad, acc ← (acc << 1) ^ (f ? poly : 0),
the spec's register in the direct form, any width to 16 with the polynomial
left-aligned. `ACC_OUT pin`: the pin takes acc[15], then acc shifts left,
the CRC out MSB first. `ACC_PUSH`: the RX FIFO takes acc[7:0], then acc
shifts right by eight; it stalls on a full FIFO as PUSH does. `ACC_LOAD`:
poly ← {shift_reg, poly[15:8]}, a polynomial byte from the host, low first.
With poly = 1 it is a plain sixteen-bit shift register. With poly = 0x8000
it is the parity bit.

### Encoding

Every word is one the ISA rejects today, and no valid word changes meaning:

| | where | new words |
|---|---|---|
| far SKIP, SKIP8 / 16 / 24 | opcode 110, flag clear, bits 6:4 the index's high part, which SKIP's shape rejects | 512 for W16, 1536 for W32 |
| SKIP_PIN | NOP's hole, bits 7:3 = 01100, pin in 2:1, level in 0 | 256 |
| SHIFT_IN1, SHIFT_IN01 | the shift word's spare bit 0, bits 1:0 = 11 and 01 | 2304 between them |
| PUSH1 | the pull/push word's spare bit 1, bits 1:0 = 11 | 288 |
| SKIP1 | opcode 110, flag clear, bits 6:4 = 001 | 512 |
| ACC_IN, ACC_OUT, ACC_PUSH, ACC_LOAD | NOP's hole, bits 7:5 = 001 | 320 |

## The CRC programs

Every tree form is `crc4_lfsr.asm`'s method at the width its candidate
holds. The register is kept from its input end, the Fibonacci form. The
parity is two paths through SKIPs that meet on pin 1, cleared by the
cell's first word and set on the odd paths, then sampled back in. The CRC
leaves by one observation: the register's top bit is the feedback with a 0
in, the same tree, and a 0 fed back in its place shifts the register on
without feedback. So the emission cell is the data cell with pin 3, held at
0, as the input and as the feedback.

| | W32 | Pin16 | Acc | W16 | Pin8 | Lanes |
|---|---|---|---|---|---|---|
| CRC-15 computable | **yes** | **yes** | **yes** | no | no | no |
| the widest it holds, direct | 16 | 16 | 16, any polynomial | 8 | 8 | 8 |
| program | `crc15_w32` | `crc15_pin16` | `crc15_acc` | `crc8_w16` | `crc8_pin8` | `crc8_lanes` |
| window | f(t−1−i) at age 2i+1, the input at 0 | f(t−1−i) at age i | the spec's register | as W32 | as Pin16 | input in lane 0, window in lane 1 |
| words | 180 | 171 | **23** | 100 | 91 | 100 |
| distinct words | 90 | 87 | 8 | 46 | 43 | 46 |
| words in a data cell | 35, the parity 31 | 34 | **2** and the REPEAT | 19 | 18 | 19 |
| cycles an input bit | 13 to 20 | 12 to 19 | **3** | 9 to 12 | 8 to 11 | 9 to 12 |
| cycles a CRC bit out | 12 to 17 | 10 to 15 | **2** | 8 to 11 | 6 to 9 | 8 to 11 |
| new state bits | 24 | 1 + 8 | 32, acc and poly | 8 | 1 | 8 |
| new logic, on paper | a 24-bit stage, SKIP's mux 8 to 32 | a pad latch and mux, the stage | 16 XORs, a left shift, a right shift by 8, a load, a push mux | a stage, mux 8 to 16 | a pad latch and a 4:1 mux | a second shift path, an 8:1 mux, a push mux |
| new words | 1536 | 768 | 320 | 512 | 256 | 3104 |
| stalls | none new | none new | ACC_PUSH on a full FIFO, the side effect none | none | none | PUSH1 as PUSH |
| restart | clears the stage | clears it | clears acc and poly | clears the stage | nothing to clear | clears the lane |

The pin latch is one flop: SKIP decides on its last cycle from the
register as it stood when it issued, and a pad can change during a delay
where a register cannot, so SKIP_PIN keeps what it saw.

**Two 8-bit lanes do not make CRC-15 possible.** The window needs fifteen
feedback bits that shift together, and the lanes do not cascade. Copying
lane 1's oldest bit into lane 0 through a pin each input bit would put the
copies beside the inputs, four of each, for a window of about twelve. That
is arithmetic, not built. A sixteen-bit lane would hold the window and pay
about Pin16's numbers plus a sample word a bit.

## The receivers: destuffed bytes to the host

`can_rx_bits_C.asm`'s cell with the data bit gathered in the second
register and pushed a byte at a time. The raw history stays in
`in_shift_reg` for the run test, and a stuff bit goes into it alone. This
is RX6, the stage the current ISA refused at 1629 words for nineteen bits.

| | Lanes, `can_rx_bytes_lanes` | Acc, `can_rx_bytes_acc` | today, `can_rx_bits_C` |
|---|---|---|---|
| to the host | 6 bytes a frame, the destuffed stream | the same | 42 bytes, one bit each |
| clocks a bit | 8 | 8 | 8 |
| words | 82 | 96 | 27 |
| distinct words | 46 | 48 | 21 |
| the data sample | the raw sample, one SHIFT_IN01 on the sixth clock's level | a word later, ACC_IN, the seventh clock's level | the raw sample |
| the host may sleep, for this frame | 33 bit times | 33 bit times | 4 bit times |

Both are exact on the six frames, the ACK lands, and nothing stalls. The
words are the eight cells a byte needs, a body run five times, where the
one-bit form's body is one cell. A glitch on the sixth clock flips the byte's bit
on the lanes. On the accumulator a glitch on the sixth clock touches the
raw history alone, and one on the seventh the data alone.

## What each does for CAN, and beyond

The CAN rows are measured unless they say otherwise. The last row is by the
shape, except the parity, which is pinned.

| | W32 | Pin16 | Lanes | Acc |
|---|---|---|---|---|
| CRC-15 | yes, 180 words | yes, 171 words | no, CRC-8 | yes, 23 words |
| inside a CAN bit, beside stuffing at 8 clocks | no: 13 to 20 cycles an input bit | no: 12 to 19 | no | one ACC_IN a data bit, a cycle; plausible, not built |
| beside the 233-word frame in 256 | no | no | no | the frame's cells gain a word each and the emission is two; plausible, not built |
| the RX collision | no: still one register | no: SKIP_PIN reads the pad but the run test still needs the raw history in the register | **yes**: destuffed bytes, 8 clocks | **yes**, with poly = 1 |
| RX with the CRC check at once | no | no | no | no: the accumulator is the data register or the CRC, not both |
| elsewhere | a longer reach for SKIP | SWD's and I²C's ACK read without a sample slot | a second input stream, dual-line inputs | SWD's parity, which `swd_write.asm` takes from the host because the core has no XOR: x + 1 is the accumulator's width-1 case, pinned; CRC-8 for SMBus and 1-Wire, CRC-16 for HDLC and USB, CRC-7 for SD; a sixteen-bit second stream |

## Findings

1. **Width alone makes CRC-15 computable and nothing else.** W32 computes
   it, 180 words at 13 to 20 cycles an input bit. It fits no CAN bit and no
   frame, and it leaves RX exactly where it was. The thirty bits the
   baseline predicted were the thirty the program needed.

2. **An input that does not take a slot halves the width, as predicted.**
   Pin16 computes CRC-15 with a sixteen-bit window: 9 bits of new state
   for W32's 24, and a cell a word and a cycle shorter. It does nothing for
   RX: the run test still wants the raw history in the register.

3. **Two lanes solve RX and not CRC-15.** A second independent register
   gives the receiver its destuffed bytes at eight clocks a bit, and the
   host its slack back, 33 bit times for 4. But the lanes do not cascade,
   so CRC-15's fifteen-bit window does not fit. CRC-8 is the widest direct.

4. **The accumulator is the only candidate that makes CRC cheap.** 23
   words and 3 cycles an input bit for 171 to 180 and 12 to 20. It is the
   only form whose CRC could live inside a CAN bit beside stuffing, and
   the only one that could sit beside the frame in 256 words. The tree
   forms prove the CRC computable. They do not make it usable.

5. **The accumulator is a second stream register with XOR feedback, and
   that is why it is not CAN hardware.** With poly = 1 it is Lanes' second
   register at sixteen bits, and it solves the RX collision as the lanes do,
   exact at eight clocks a bit. With poly = 0x8000 it is SWD's parity, the
   gap `swd_write.asm` records. Loaded with other polynomials it is the
   CRC of five other protocols. The XOR feedback is what turns 171 words
   into 23. Without it, a second register makes CRC-15 correct but not
   usable.

6. **No candidate gives a receiver all three streams at once.** A full CAN
   receiver wants the raw history, 5 bits for the run test, the data, 8,
   and the CRC, 15. Every candidate here gives two registers at most. The
   accumulator is the data register or the CRC, not both, in the same
   frame. That is the combined program's question, not this round's.

7. **So the answer to the round's question is a second stream register
   with optional feedback.** A second register the input can enter
   independently of `in_shift_reg` explains the RX collision. Sixteen bits
   of it and an XOR feedback path explain the CRC wall. W and Pin answer
   the CRC question only, Lanes the RX question only, and Acc both, one at
   a time, at 32 bits of state: the most of any candidate here.

## Decided

The reviewer's call, 2026-09-28.

| | |
|---|---|
| W32 | rejected. Width alone: correct, 180 words at 13 to 20 cycles an input bit, and nothing for RX |
| Pin16 | rejected. An elegant proof that an input without a slot halves the window, as the baselines predicted, but still 171 words at 12 to 19 cycles, and nothing for RX |
| Lanes | rejected as a separate feature, subsumed: it found half of the answer. The accumulator is Lanes widened to sixteen bits with a feedback path |
| Acc | **adopted**: a sixteen-bit second stream register with optional LFSR feedback. Two failures, CRC's width and RX's collision, converged on it, and it turns the CRC from computable into usable, 171 to 180 words into 23 |

One refinement before the ISA froze, the reviewer's: the candidate's one
input word, the shift with feedback, was a plain register only with poly =
1 and a push every eight bits, before anything reached bit 15; shifted
further, the old top bit fed back. The adopted accumulator says which in
the word, not in hidden mode state: `ACC_IN pin`, the plain shift, the
oldest bit falling off bit 15, and `ACC_CRC pin`, the shift with feedback.

### The spec

```
  15 14 13 | 12 .. 8 | 7 6 5 | 4 3 2 | 1 0
   0  0  0 |  delay  | 0 0 1 | kind  | pin
```

NOP's hole, bits 7:5 = 001, which the CAN round's SKIP_SENT had been
measured in. kind 000 `ACC_IN pin`: acc ← (acc << 1) | gpio_in[pin]. 001
`ACC_CRC pin`: f = acc[15] ^ gpio_in[pin], acc ← (acc << 1) ^ (f ? poly :
0). 010 `ACC_OUT pin`: gpio[pin] ← acc[15], acc ← acc << 1, through the one
pin-write port. 011 `ACC_PUSH`, pin bits 0: the RX FIFO takes acc[7:0],
acc ← acc >> 8, stalling while the FIFO is full as PUSH does. 100
`ACC_LOAD`, pin bits 0: poly ← {shift_reg, poly[15:8]}. Kinds 101 to 111
stay rejected. The pad is sampled as SHIFT_IN samples it, as the word
issues. acc shifts towards bit 15 whatever `shift_dir` says, since a CRC is
defined MSB first. A delay as any word, no side effect. Reset and restart
clear acc and poly. 448 words that were rejected are instructions, and no
other word changed meaning. CAN's CRC-15 is poly = 0x8B32, 0x4599
left-aligned; the parity is poly = 0x8000.

In the model (`sim/cpu.py`) and pinned on it (`tests/test_acc.py`): the
words and the 448, every program the same words, the plain shift over forty
samples, the CRC against the oracle for five polynomials, the parity among
them, ACC_OUT, ACC_PUSH and its stall, ACC_LOAD, the sample as the word
issues, reset and restart, and nothing else moved. The candidate programs
on the adopted ISA: `experiments/acc/crc15.asm`, 23 words, and
`experiments/acc/can_rx_bytes.asm`, 92 words, the polynomial load gone. The
candidate rounds stay measured on the ISA they ran on
(`experiments/can/candidates.py`, `round_isa`). In `core.v`: acc and poly, sixteen bits each, decoded
from NOP's hole; the feedback is sixteen XORs gated by acc[15] ^ the pad;
ACC_PUSH shares PUSH's stall and the RX FIFO's port through a mux; ACC_OUT
writes its pin beside SHIFT_OUT's. RTL against the model on every word from
random state, the accumulator words in the random REPEAT bodies and the
adversarial sweeps, and both programs at the pins (`rtl_tests/core_tb.py`,
`top_tb.py`).

## Files

- `experiments/crc/candidates.py`: the models; `Variant` adds the word order a far SKIP needs and the run test
- `experiments/crc/gen.py`: writes every program below
- `experiments/crc/crc15_{w32,pin16,acc}.asm`, `crc15_acc_bytes.asm`: CRC-15 on the three candidates that hold it
- `experiments/crc/crc8_{w16,pin8,lanes}.asm`: the widest CRC on the three that do not
- `experiments/crc/can_rx_bytes_{lanes,acc}.asm`: the destuffing receiver handing the host bytes
- `tests/test_crc_candidates.py`: the words, the semantics, the programs against the oracle, the receivers, the numbers
