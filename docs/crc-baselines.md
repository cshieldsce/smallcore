# CRC-15 on the current ISA: three baselines

**Outcome (2026-09-28): nothing merged, no candidate named.** The question,
kept apart from the frame: given a known bit stream, the SOF, the
identifier, the control field, the DLC and the data, can the core as it is
produce CAN's CRC-15 over it? Python is the oracle (`tests/test_crc.py`).
The answer is no, and the part that fails is the width of the state: the
core has eight bits a program can both write and read, and the computation
wants fifteen, thirty in the form the core can execute. The XOR is not the
wall, and neither is writing the state back, once the register is looked at
from its input end. Nothing in `isa.yaml`, `sim/cpu.py` or the RTL changes;
the frame keeps its host-computed CRC.

Arbitration was information the control flow could not see; stuffing was
information that was expensive to test. CRC is a third kind: the machine
lacks the state. Before any candidate, exactly which part is pinned, by the
five questions the review asked: the state's width, the XOR, getting the
sent bit into the computation, writing the result back, and which of those
together.

## The state a program can hold

Every valid word with no delay, run once from random state and twice over,
and what it changed recorded per instruction; then every kind of word run
from a state and from the same state with one field different, and where
the difference showed up recorded as what the word read
(`test_what_each_instruction_writes`, `test_what_each_instruction_reads`,
the whole table asserted).

| state | bits | written by | read by |
|---|---|---|---|
| `pc` | 9 | JMP, SKIP, REPEAT, else the next word | – |
| the delay counter | 5 | every word's bits 12:8 | – |
| `rc` | 5 | REPEAT | REPEAT, into the pc |
| `shift_reg` | 8 | PULL, whole, from the host's FIFO; SHIFT_OUT, a shift with zero fill | SHIFT_OUT, one bit onto pin 0 |
| `in_shift_reg` | 8 | SHIFT_IN, one bit at one end | SKIP, one bit into the pc; PUSH, whole, to the host's FIFO; and, since 2026-09-28, SKIP_RUN and SKIP_NORUN, the newest n bits into the pc, which changes nothing below: the width is the wall |
| `gpio` | 4 | SET, SHIFT_OUT's own bit, and any word's side effect: a constant | nothing. The pad's readback is an input, which SHIFT_IN samples and WAIT holds on |
| `open_drain`, `shift_dir` | 4, 1 | CONFIG | the pad; the shifts |
| the TX FIFO | 4 × 8 | the host | PULL |
| the RX FIFO | 4 × 8 | PUSH | the host |

What stalls a word, a pin's level or a FIFO's fullness, holds its side
effect and its load with it; nothing else reads anything. So the state a
program both writes and reads is `in_shift_reg`, eight bits, written one at
a time at one end and read one at a time into the pc, and the four pins,
written as constants and read only by sampling the pad back into the
register, which costs a register slot. A bit moves from the register to a
pin only through the pc, SKIP then SET, and every XOR is control flow.

## What CRC-15 asks

The spec's register, fifteen bits, and for every input bit: f = in ^
crc[14]; crc = (crc << 1) ^ (f ? 0x4599 : 0). Read the top bit, XOR it with
the input, shift, and where f is 1 flip six bits in place, 14, 10, 8, 7, 4
and 3, and set bit 0.

## What fails, exactly

1. **The width of the state: fails, first.** Fifteen bits that software
   writes and reads; the core has eight. The pins add four that can be read
   only by displacing register bits; `shift_reg` and the FIFOs are the
   host's; `rc` and the counter are read by nothing. No path holds a
   fifteen-bit value.

2. **The XOR: does not fail.** The parity of n register bits is control
   flow: two paths through SKIPs, one per parity so far, that meet on a pin,
   cleared by the first SKIP's side effect and set on the odd paths, then
   sampled back into the register. Measured: two inputs, 8 words, 4 or 5
   cycles; three inputs in the CRC-4 cell, 13 words of a 17-word cell, 6 to
   9 cycles of its 8 to 11.

3. **Getting the sent bit in: does not fail.** The bit goes out on pin 0
   and comes back from the pad into bit 0 of the register, as every CAN bit
   already does for stuffing. It costs what stuffing paid: a register slot
   per bit, which halves the history the register holds.

4. **Writing the state back: fails in the spec's form, and a change of
   basis takes it off the table.** `in_shift_reg` is written at one end
   only. A bit in the middle cannot be flipped, and rebuilding the register
   through a pin needs the old copy to survive while the new one shifts in:
   after j shifts the old bit i is at i + j, and new bit k wants old bit
   k − 1, at 2k − 1, so only the low half of the register can be rebuilt,
   whatever its width. But the spec's register seen from its input end is a
   Fibonacci LFSR: the bit it feeds back depends on the last w feedback
   bits alone, f_t = in_t ^ XOR over i of P[w − 1 − i] f_{t−1−i}, and the
   register itself is a fixed function of the same window, crc_t[k] = XOR
   over i ≤ k of P[k − i] f_{t−1−i}. Then the shift that takes f in is the
   only write, and the conversion at the end is w more parities. Checked on
   the model against the spec's register for CAN's polynomial, the 4-bit
   one and an 8-bit one, every length to 2w + 2 and the frames' lengths
   (`test_the_register_is_a_function_of_its_last_feedback_bits`).

5. **Together:** width alone fails. In the form the core can execute the
   window is w feedback bits interleaved with w input bits, so CRC-15
   wants thirty bits of register and CRC-4 fits in eight; in any form it
   wants fifteen, and the machine has eight. The XOR would cost a
   nine-input parity a bit, about 30 words and 16 cycles by the CRC-4
   cell's rate, and the final conversion fifteen parities of up to seven
   terms, if there were somewhere to keep the window.

## The three baselines

| | the host's CRC | CRC-4 on the ISA | the CRC as data |
|---|---|---|---|
| where | stage 5A, `can_tx_frame.asm` | `experiments/crc/crc4_lfsr.asm` | stage 5A, the same program |
| what | the host computes 15 bits over 27 and writes them as `CRC[14:7]`, `{CRC[6:0], 0}` | four host bytes out on pin 0 and back through the pad, the window kept in the register, the feedback bit on pin 1, the CRC-4 to the host in the low nibble of one byte | the frame's body sends the CRC bits as it sends every bit: no word is the CRC's, a wrong CRC goes out bit for bit (`test_the_crc_is_data_to_the_frame_transmitter`) |
| width | 15 | 4: the widest with eight bits of register | 15 |
| words in the core | 0 | 101, 43 distinct: 18 a byte, a PULL and a 17-word cell as a body of eight, the four bytes written out since a PULL breaks a body; 27 for the conversion; 1 CONFIG | 0 |
| cycles an input bit | 0 | 8 to 11 by the path, 9 when everything is 0; 308, 302, 323 cycles for the three vectors, 32 bits each | 16, a stream bit's |
| state | the host's | `in_shift_reg`: the input bits at 1, 3, 5, 7 and the feedback bits at 0, 2, 4, 6 after a cell, the parity reading bits 0, 5 and 7, the input and the polynomial's taps; pin 1 | `shift_reg`, as any data: 15 of the 42 stream bits, 2 of the 6 bytes, the one pad bit |
| the host's part | the computation, in whatever it is | 4 pushes, 1 pop | the computation and 2 bytes |
| beside stuffing in a 16-cycle bit | nothing to fit | no: SHIFT_OUT, SHIFT_IN, the seven-cycle tree and a parity of 8 to 9 cycles is 17 to 20, and the register is the stuffing's window too | fits: it is the frame |
| at the pins | `top_tb.can_data_frame_at_the_pins` | `top_tb.crc4_lfsr_at_the_pins`, clock for clock the model's under the pad readback | the same |

CRC-4 is not CAN's and is here to measure the mechanism at the width there
is room for: the parity as control flow, the register as the window, the
pin as the XOR's output, the conversion at the end, and the number the
review asked for, the CRC's equivalent of SWD's 64 words for 32 bits: 17
words and 8 to 11 cycles a bit for four bits of CRC, and no width to grow
into.

## Findings

1. **CRC-15 fails on the width of the state, before any XOR is written.**
   Eight bits that software writes and reads, fifteen wanted. The third
   kind of failure CAN has found: not a bit the control flow cannot see,
   not a test that is expensive, but state that is not there.

2. **The XOR is control flow and is affordable at small widths.** Two
   paths through SKIPs meeting on a pin: 8 words for two inputs, 13 for
   three; 4 to 9 cycles. It is the pin that makes it possible: the only
   place a computed bit can be put, and SHIFT_IN the only way to bring it
   back.

3. **The shift register is the LFSR, seen from its input end.** The
   Fibonacci form makes the shift the only write, so writeback is not a
   wall, and the register's own bits come back at the end by w parities.
   This is the shape any candidate would build on, whatever its width.

4. **Every input bit costs a register slot.** The register is the window
   and the sample buffer at once, so it holds half its width of history:
   CRC-4 in eight bits, and CRC-15 would want thirty. A candidate that
   reads the pad without a shift, or a window the input does not enter,
   halves the ask.

5. **The CRC as data costs the core nothing.** The frame sends it as it
   sends the identifier; the seam is the host's byte cut and one pad bit.
   The host's CRC and the CRC as data are the same baseline from two
   sides: the computation is separable from the wire.

6. **Program capacity again.** CRC-4's 101 words beside the frame's 233
   would be 334 in a 256-word program, if the width were there; a CRC-15
   in the same style would be near 200 on its own. The 256-word limit is
   on the inventory in its own right (README, "Design pressures").

7. **What would earn a word is not an XOR.** An XOR against what? Without
   somewhere to keep fifteen bits, an XOR instruction solves nothing. The
   shapes that could, a small generic register with shift and XOR, a
   configurable LFSR accumulator, or something in the existing shift
   state, are different architectures, and none is named here: RX and
   de-stuffing speak first, and the candidates after.

## Files

- `experiments/crc/crc4_lfsr.asm`: the widest CRC on the current ISA, 101 words
- `tests/test_crc.py`: the oracle and its identity with the Fibonacci form; the census of what each word writes and reads; the CRC-4 program against the oracle on 236 streams, the window in the register, the numbers; the CRC as data in the frame
- `rtl_tests/top_tb.py`, `crc4_lfsr_at_the_pins`: the program on `top.v`, the pads read back, clock for clock the model's
