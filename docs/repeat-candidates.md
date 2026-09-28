# Repeat candidates against the SWD programs

**Outcome (2026-09-27): A adopted.** `REPEAT count, label` is opcode 111 in
`isa.yaml`, the counter `rc` is in `sim/cpu.py`, the rules are the
assembler's (`cpu.check_bodies`), and the corners below are pinned on the
model itself in `tests/test_repeat.py`. One correction to the spec as first
written: `rc` holds the runs still to go after a REPEAT commits, at most 31,
so it is five bits, not six. The comparison below is left as it was made.

SWD made one architectural complaint (README, "SWD by the numbers"): the same
two-word bit cell, a shift and its clock edge, 32 times over. 64 of the read's
103 words and of the write's 106 are the data bits; 89 and 90 words repeat an
earlier word exactly. The core has every operation SWD needs. It cannot say
"again".

This compares four ways to say it. Method as before: no change to the core.
Each candidate is isa.yaml plus its word or two and a model that runs them
(`experiments/repeat/candidates.py`), spliced into the exact `swd_read.asm` and
`swd_write.asm` wherever a body repeats: the request's eight cells, the ACK's
three, the four data bytes. The loop word costs a cycle; that cycle is taken
from the delay of a word next to it, so a candidate can be held to the
baseline's wire cycle for cycle, with a target that says OK, WAIT then OK or
FAULT, a host late with the request again, a PUSH or PULL stalling inside the
repeated body, and a restart in the middle of a loop
(`tests/test_repeat_candidates.py`). The existing suite is then run on each
candidate's model in place of the model (`experiments/repeat/suite.py`) to see
what it disturbs. `programs/swd_read.asm` and `programs/swd_write.asm` stay as
they are: they are the baseline and the evidence.

## The candidates

**A, `REPEAT count, label`.** A counted backward branch at the end of the body:
back to `label` until the body has run `count` times, 1..32. One counter, 0
between loops; the first arrival loads it, every arrival takes one off and
jumps back while the result is not 0. One word per loop, one cycle per
iteration. `count - 1` sits in bits 12:8, where every other word has its
delay: REPEAT has no delay of its own; the operand byte is the distance back
to the label, so the reach is bounded and the program is not. No nesting:
one counter. The spec as it would be written is below, "REPEAT, the spec".

**B, `REPEAT_NEXT count`.** The next word runs `count` times before pc moves
on. One 5-bit counter, one cycle once. Bodies of one word only.

**C, `LOAD count` / `DJNZ label`.** The conventional shape: one word loads a
5-bit counter, another decrements it and branches while it is not 0. Two words
per loop; the LOAD may sit anywhere before the loop, on any path. The two share
the free opcode on operand bit 7, so DJNZ's target is 7 bits: programs of at
most 128 words, or the count moves into the delay bits as in A. No nesting.

**D, `BURST_OUT` / `BURST_IN`.** SHIFT_OUT or SHIFT_IN eight times from one
word: each cell is the shift with its side effect, held 1 + delay cycles, then
the side pin returned to the other level for 1 + delay cycles. `BURST_IN 0, 1,
1 [3]` is `SHIFT_IN 0, 1, 1 [3]` and `SET 1, 0 [3]` eight times over, less the
eighth return, which is left to the next word: a PUSH, a PULL's clock word,
whatever the protocol puts there. Encoded in bit 0 of the SHIFT word, spare
until now (bits 1:0: SHIFT_OUT 00, BURST_OUT 01, SHIFT_IN 10, BURST_IN 11); no
new opcode, no count. State: which cell (3 bits) and which half (1 bit). Eight
because the registers are eight wide: a burst is a byte. Nothing can happen
inside one and it never stalls. This is the reviewer's B made to fit the SWD
body by folding the cell's second word, the clock's return, into the first.

## What each does to the SWD programs

Words, by section, both programs. The baseline's sections: request 16, ACK 6,
read data 65 (the ACK's PUSH on the OK path and 64), write data 72 (a PULL, 68,
the parity's 3).

| | baseline | A | B | C | D |
|---|---|---|---|---|---|
| request, 8 cells | 16 | 3 | 16 | 4 | 2 |
| ACK, 3 cells | 6 | 3 | 6 | 4 | 6 |
| read data, 4 bytes of 8 | 65 | 18 | 65 | 19 | 9 |
| write data, 4 bytes of 8 | 72 | 22 | 72 | 22 (+1 LOAD on the common path) | 16 |
| **read, words** | **103** | **40** | 103 | **43** | **33** |
| **write, words** | **106** | **40** | 106 | **43** | **36** |
| distinct words, read / write | 14 / 16 | 20 / 20 | 14 / 16 | 23 / 23 | 15 / 17 |
| cycles, read / write | 379 / 384 | same | same | same | same |
| wire cycle for cycle: OK, WAIT then OK, FAULT, host late with the request | | yes | not spliced | yes | yes |
| a PUSH or PULL stalling inside the body: wire the same, count untouched | | yes | | yes | yes |
| restart mid-loop: a fresh run from there | | yes | | yes | yes |

B has nothing to repeat in SWD: no word in either program is followed by
itself. Where a cell is one word, `uart_tx_pull.asm`, B makes 11 words 5 and D
makes them 4, the frame the same to the cycle.

Host interactions and FIFO fill do not change with any candidate: the same
PUSHes and PULLs happen at the same cycles.

## Encoding and state

| | new opcode | operand bits | other bits | state | words per loop | cycles per iteration |
|---|---|---|---|---|---|---|
| A | 111 | back, 8: pc - back | bits 12:8 are count - 1, not a delay | 5-bit counter | 1 | 1, taken from a delay |
| B | 111 | count, 5 | delay bits unused | 5-bit counter | 1 | 0; 1 once |
| C | 111, two forms on operand bit 7 | LOAD count 5; DJNZ target 7 | delay as ever | 5-bit counter | 2 | 1, taken from a delay |
| D | none: bit 0 of the SHIFT word | as SHIFT | delay as ever, the half period | 3-bit cell counter, 1-bit half | 0 | 0 |

In gates, on paper: A and C are a 5-bit register, a decrement, a zero test and
the branch mux JMP already has; A also gates the delay counter's load for its
one word; C has one more decode. B is the counter and a hold on pc. D is a
3-bit counter, a phase bit, an inverter on the side effect's value in the
return half, a hold on pc and a gate on the shift enable.

## Where else each would serve

By the shape of the cell, not run, except the UART, which was.

| cell | shape | A | B | C | D |
|---|---|---|---|---|---|
| UART TX, RX | one SHIFT, no side effect | yes, 2 words for 8 | yes, 2 for 8 | yes, 3 | yes, 1 for 8 |
| SPI TX | SHIFT_OUT + SET | yes | no | yes | yes |
| SPI duplex | SHIFT_OUT + SHIFT_IN | yes | no | yes | no: the return half would have to sample |
| I²C write | SET, SHIFT_OUT, SET | yes | no | yes | no: SDA moves after SCL falls, not with it |
| I²C with stretching | SET, SHIFT_OUT, SET, WAIT | yes: the WAIT stalls, the count waits | no | yes | no |
| SWD ACK, 3 cells; parity, 1 | | yes | no | yes | no: eight or nothing |

## What each disturbs

The existing model suite, 2555 tests on the ISA as it is, run on the
candidate's model in place of the model. The copy of the step with nothing
added passes all 2555. The counts differ by candidate because the adversarial
sweep enumerates the ISA's words: more words, more cases. One test is left
out for every candidate: it waits for the halt with no cycle cap and stops on
a JMP, because in the ISA as it is nothing else goes backward; under B a
repeated PULL empties the FIFO and stalls forever, under C a DJNZ loop does.

| | passes | fails | what the failures are |
|---|---|---|---|
| A | 2479 | 331 | 256 cases of "a delay only holds the state the first cycle produced": REPEAT's bits 12:8 are not a delay. 70 random programs whose 111 words are now REPEATs. 5 tests that pin the ISA as it is: the free opcode, the side effect on every word but JMP, bad words rejected, the valid word count, the random walk's kinds of cycle |
| B | 2488 | 98 | 93 random programs whose 111 words are now REPEAT_NEXTs, and the same 5 ISA-as-it-is tests |
| C | 2687 | 27 | 22 random programs whose 111 words are now LOADs and DJNZs, and the same 5 |
| D | 2429 | 210 | 165 random programs whose SHIFT words with bit 0 set are now bursts. 40 cases of "a side effect changes exactly one pin and nothing else": a burst writes its side pin twice per cell, sixteen times per word. 5 ISA-as-it-is tests: bad words rejected, the side-effect field, SHIFT one opcode with an in bit, the valid word count, the random walk |

These are not programs breaking. Every program in `programs/` assembles to
the same words under every candidate and every word decodes to the same
instruction (`test_every_existing_program_means_the_same_under_the_candidate`).
The failing tests encoded assumptions about the whole 16-bit word space: that
opcode 111 is not an instruction, that bits 12:8 are a delay in every word,
that a word writes at most one pin. A spec evolution cost, not a regression;
once a word is adopted those tests are rewritten to the new contract. What
the candidates disturb is the hardening suite's model of a word: one
operation on its first cycle, hold 1 + delay, then pc + 1 or the JMP target,
one pin write at most, and only JMP goes backward. A breaks the meaning of
bits 12:8 for one word and goes backward; B holds pc on a word that is not
its own; C goes backward; D breaks one operation and one pin write per word.
Whichever is chosen, that model gets a clause, and the RTL differential
tests get the same clause.

## Findings

1. **The complaint is real and cheap to answer.** Any counted loop takes the
   two programs from 103 and 106 words to about 40 with the wire unchanged to
   the cycle. The core did not need a new operation, a new pin mode, a wider
   FIFO or arithmetic: a 5-bit counter and a branch.

2. **A loop word's cycle has to come from somewhere, and not from before a
   word that can stall.** The first write splice ended the body `SET 1, 1
   [1]`, `PULL`, `REPEAT`, the REPEAT's cycle taken from the SET. A prompt
   host saw the baseline's wire; a host late with a byte saw the write run one
   cycle longer, SWCLK high one cycle more: the PULL began its stall a cycle
   earlier than the baseline's and the loop word's cycle then fell after the
   byte arrived. With the PULL first in the body and the loop word before it,
   the stall begins and ends as the baseline's
   (`test_a_loop_word_right_after_a_stalling_word_moves_the_stall_by_a_cycle`).
   The read had no such problem because its stalling PUSH carries its own
   delay after the stall. A prefix form that costs no cycle per iteration,
   `REPEAT count, span` before the body, PIO's wrap with a count, would not
   have the rule, at the price of a start address and a span register and a
   compare on pc every cycle; not built.

3. **A over C.** Same counter, same reach; C spends a second word per loop and
   a select bit, and its 7-bit absolute target caps programs at 128 words, or
   it takes A's delay-bit trick anyway; A's distance back caps the body at
   255 words and the program at nothing. C's one gain is that the LOAD floats: the
   write's data count loads on the common path, harmlessly, on WAIT and
   FAULT too. A's cost is the one word whose bits 12:8 are not a delay; the
   suite says so 256 times.

4. **B is out**, as predicted: the SWD cell is two words. Where the cell is
   one word, UART, B does what A does at the same size.

5. **D is the smallest program and the smallest encoding, and the narrowest.**
   33 and 36 words, no new opcode, four flip-flops. It serves a shift with a
   clock edge and nothing else: not the 3-bit ACK, not the parity bit, not
   SPI duplex, not I²C, not a body with a WAIT in it. It also ends the rule
   the hardening track is about to pin, one pin write per word: a burst
   writes its side pin sixteen times. Its virtue is that it names what the
   repetition actually is in every protocol here so far: the cell's clock
   edge going back.

6. **Stalls are safe in all of them**, by construction: the count changes
   only when the loop word commits (A, C), when the repeated word commits (B),
   or when a cell completes (D, which never stalls). A PUSH stalling for 300
   cycles inside a body left every count where it was. Restart clears all of
   it as it clears the delay counter.

7. **None of them nest.** One counter each. SWD did not need two: the 4-byte
   loop is unrolled at the byte, the byte at the bit, and the two loops are
   sequential. Nothing here asks for a second counter.

8. **The 3-bit ACK and the 1-bit parity are why the count is a count** and
   not "eight": D cannot touch them, A and C fold the ACK's six words to
   three.

## REPEAT, the spec

The word, as isa.yaml would carry it:

```
  15 14 13 | 12 11 10 9 8 | 7 6 5 4 3 2 1 0
   1  1  1 |   count - 1  |      back
```

`REPEAT count, label`: `count` 1..32 total runs of the body, held as
`count - 1`; `back` 1..255, the body's length in words, the label being
`back` words before the REPEAT. One cycle. No delay: bits 12:8 are the count.
No side effect: no bits are left for one, and the assembler refuses one.

The counter `rc`, five bits, is 0 while no loop is under way. It changes on
the REPEAT's own cycle and at no other time: a REPEAT arriving with `rc` 0
loads `count - 1`, the runs still to go; every other arrival takes one off;
pc goes to pc - back while the result is not 0, else to pc + 1. (As first
written this said six bits and "loads count, takes one off": the same thing
one step later, and the register never holds the 32.) A back past word 0
wraps the nine-bit pc past the end, halted; the assembler never writes one. A body word stalling on a FIFO or a pin
does nothing to `rc`; a delay does nothing to `rc`; a SKIP or JMP does
nothing to `rc`. Reset and restart clear it, as they clear the delay
counter; a slot change is a restart.

Rules the assembler enforces, so that no machinery is spent on odd control
flow: a body holds no REPEAT (no nesting, no overlapping bodies); a JMP in a
body lands in it, from the label to the REPEAT; the body's last word is not
a SKIP, which would step over the REPEAT; nothing outside jumps or skips into
a body past its label. Entering a body at its label from outside is the
ordinary entry: the SWD WAIT retry's `JMP request` does it, arriving with
`rc` 0 because the loop before it finished. Outside the rules the hardware
still does the one thing above with whatever `rc` holds, deterministically,
and touches nothing else.

The scheduling rule, for the program author: REPEAT costs a real cycle, so
when a waveform is to be kept the cycle comes out of a delay next to it, and
never from the word before a word that can stall (finding 2).

Corners pinned in `tests/test_repeat_candidates.py` on the candidate and in
`tests/test_repeat.py` on the model, each against the unrolled program under
random outside worlds: count 1, 2 and 32; a one-word
body; a 255-word body, the program then 256 words, and a 256-word body
refused; a PULL as the body's first word and a PUSH as its last, both
stalling again and again across 32 iterations with `rc` watched every cycle;
restart at every cycle of a loop, and a slot change at every cycle; each
assembler rule refused; what the rules allow (a SKIP landing on a label, two
loops in a row) running as unrolled; no side-effect bits.

## Cross-protocol applicability

REPEAT spliced into every program in the ROM's manifest, the canonical
programs untouched, each variant held to its canonical program in lockstep
under ten random outside worlds (the same pins every cycle, the same bytes
into the TX FIFO at random moments, the same pops), agreeing every cycle on
the pins, the pads, the stall and both FIFOs.

| program | canonical | with REPEAT | the cell |
|---|---|---|---|
| uart_tx_0x55 | 11 | 4 | a high and a low, five times |
| uart_tx_pull | 11 | 5 | SHIFT_OUT, eight times |
| uart_tx_loop | 12 | 6 | SHIFT_OUT, eight times |
| uart_rx | 12 | 6 | SHIFT_IN, eight times |
| spi_tx_lsb, spi_tx_msb | 21 | 8 | SHIFT_OUT and the clock |
| spi_duplex_lsb, spi_duplex_msb | 22 | 9 | SHIFT_OUT and a sampling clock |
| i2c_write | 34 | 14 | SHIFT_OUT, SCL up, SCL down, rotated |
| i2c_write_stretch | 45 | 18 | the same with a WAIT inside the body |
| i2c_write_addr_data | 64 | 24 | two bytes, the ACK decision between |
| swd_read | 103 | 40 | request, ACK, four data bytes |
| swd_write | 106 | 40 | the same, the PULL leading the body |
| **the ROM's eleven** | **275** | **111** | |

Four independently written protocol workloads, all with a bounded bit-cell
repetition, and one control word compresses all of them without changing a
cycle. The I²C cell had to be rotated (SHIFT_OUT, SCL up, SCL down) so the
REPEAT's cycle comes from the clock's drop; the stretching variant keeps its
WAIT inside the body and the count waits with it. The ROM's words folding
from 275 to 111 is not the point, since the ROM already folds repeated words
in synthesis; the point is that every program's repetition was the same
thing.

## Decided

A, in this order: isa.yaml got the word above and the ISA-definition tests
their new contract; the adversarial suite's model of a word got its clause
(bits 12:8 are a count in one word; one word goes backward besides JMP; a
REPEAT is its body count times over with a cycle between); cpu.py got the
counter and the assembler the rules; core.v gets the counter and the
subtract next, with the RTL differential tests on the same corners; the
103- and 106-word programs stay in `programs/` as the record of why. Opcode
111's accidental self-trap went with it, which is convenient, not a reason.

For the record, how the word came to be: the core had no loop, and did not
need one while UART, SPI and I²C could be written by unrolling their bit
cells. SWD pushed that far enough to measure it, 89 and 90 of 103 and 106
words repeating an earlier one, rather than to assume loops would help. Four
ways to say "again" were compared on the model against the real programs;
the smallest general one was taken; then it was run backwards over every
earlier protocol and found to serve each without moving a cycle. The
protocol-driven method, doing what it was meant to do.

## Files

- `experiments/repeat/candidates.py`: the four models; `Candidate` is cpu.CPU's step written out with hooks
- `experiments/repeat/swd_{read,write}_{A,C,D}.asm`: the splices, commented like the baseline
- `experiments/repeat/<program>_A.asm`: REPEAT in the ROM's eleven programs
- `experiments/repeat/uart_tx_{B,D}.asm`: where B applies
- `experiments/repeat/plugin.py`, `suite.py`: the existing suite on a candidate's model
- `tests/test_repeat_candidates.py`: the comparison, pinned, on the candidates' models
- `tests/test_repeat.py`: REPEAT's corners on the model itself, and every variant against its canonical program
