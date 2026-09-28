# CAN candidates against the arbitration and stuffing programs

**No outcome yet.** This is the comparison, on the model only, for the
architecture review; nothing in `isa.yaml`, `sim/cpu.py` or the RTL changes,
and the four CAN programs stay as written: `can_tx.asm` 13 words,
`can_tx_arb.asm` 95, `can_tx_ack.asm` 21, `can_tx_stuff.asm` 224.

CAN made two complaints on the post-REPEAT ISA (README, "CAN by the
numbers"). Arbitration: a node that sent recessive and sees dominant has
lost, and once SHIFT_OUT has put the bit on the pin nothing can branch on
it, so `can_tx_arb.asm` sees the bus the way a controller behind a
transceiver does, two pins, and decides on two samples with SKIP, JMP, SKIP,
JMP, three cycles on every path. Stuffing: the last five samples sit in
`in_shift_reg` bits 4:0, but asking "all one level?" is a tree of single-bit
SKIPs seven cycles deep, so `can_tx_stuff.asm` runs at 16 cycles a bit. ACK
was boring, which says CAN as a whole is not the problem. Shared by the two:
after a sample, a decision that must land on the next bit edge, and SKIP
then JMP is a cycle longer on the taken side than on the fall-through.

Method as for REPEAT (`docs/repeat-candidates.md`). Each candidate is
`isa.yaml` plus its word or two and a model that runs them
(`experiments/can/candidates.py`), spliced into the exact
`can_tx_arb.asm` and `can_tx_stuff.asm` (`experiments/can/gen.py` writes
the splices), and held to the baseline's bus: cycle for cycle for
arbitration, won, lost on each of the identifier's six recessive bits,
unopposed for six identifiers, and with a host late with the second byte;
bit for bit for stuffing at the candidate's own bit time, six identifiers
with runs of eleven, of five then five and of none, the walking ones and
zeros and every 97th, a receiver that drops stuff bits, the same byte to
the host; a restart in the middle of a frame; a stall inside a frame with
the candidate's registers watched; every existing program assembling to the
same words meaning the same things; the sample point of every splice probed
with a one-cycle glitch; and the words each candidate adds to the word
space counted, with none changed (`tests/test_can_candidates.py`, 282
tests). The existing suite is then run on each candidate's model in the
model's place (`experiments/can/suite.py`).

## A correction first

The stage 4 inventory said REPEAT was out for stuffing, "a JMP out of the
body". It is not: the assembler lets a JMP in a body land on the REPEAT
that ends it, and every exit of the stuffing cell goes to the next bit,
which is that REPEAT. `experiments/can/can_tx_stuff_loop.asm` is the
baseline's cell as a body, on today's ISA and today's assembler: ID[7] to
ID[5] one body run three times, ID[4] with its PULL written out, ID[3] to
ID[0] a body run four times, 91 words for 224, 44 distinct for 71, the
same bits on the bus at 16 cycles a bit, the same byte to the host. The
REPEAT's cycle comes out of the sample point, the seventh clock of the bit
for the eighth (43.75% for 50%); the seven-cycle tree and the 16-cycle bit
do not change. The 224 words stay as the baseline; the comparison below
gives both. Arbitration's claim stands: its lost exit leaves the body, and
a JMP or a BRANCH out of a body is what REPEAT forbids, which no candidate
here touches (the reviewer's rule: REPEAT is not mutated).

## The candidates

**A, `BRANCH bit, level, label`.** One word, one cycle, taken or not:
pc <- pc + ahead if `in_shift_reg[bit] == level`, else pc + 1. Combined
with C and D, `BRANCH_RUN n, level, label` and `BRANCH_SAME n, label`; with
Bc, `BRANCH_SENT pin, level, label`.

**B, `SHIFT_SENT pin`.** The bit the core holds on `gpio[pin]`, the
register behind the pad, sampled into `in_shift_reg` as SHIFT_IN samples
the pad. The sent bit joins the sample stream and the decision reads two
samples as the transceiver program does, from one pin.

**Bc, `SKIP_SENT pin, level`.** The same register as a condition: step
over the next word if `gpio[pin] == level`. No sample; the decision reads
the register directly.

**C, `SKIP_RUN n, level` and `SKIP_NORUN n, level`.** The newest n samples
all `level`, n 1..8 held as n - 1, in both senses. A run test on the
register, no new state; n = 1 is SKIP on the newest bit.

**D, `SKIP_SAME n`.** A counter, three bits, of consecutive equal samples:
a sample equal to the one before makes it one more, to 7 at most, any
other makes it 1; reset and restart make it 0. The test is count >= n. The
run's level is the newest bit, SKIP 0's business.

And the combinations AB, ABc, AC, AD.

### Encoding

Opcode space is full, so every word here takes words the ISA rejects
today and changes the meaning of none it accepts; the count of each is in
the table below. The branch family is opcode 110, SKIP's, with bits 7:6 =
01, which SKIP's shape rejects (no side effect and a pin bit set):

```
  15 14 13 | 12   | 11 10 9         | 8     | 7 6 | 5 4 3 2 1 0
   1  1  0 | kind | bit / n-1 / pin | level | 0 1 | ahead 1..63
```

One cycle. No delay: bits 12:8 are the condition, as they are a count in
REPEAT. No side effect. The reach is 63 words ahead and never back, the
mirror of REPEAT's 255 back: a relative target makes every cell of a
program the same words, which a ROM folds, and the reach covers every
CAN cell here with room; what it cannot do is SWD's retry, which goes
back, see "Where else". kind 0 is BRANCH; kind 1 is the candidate's other
test, so a candidate with two tests has 2016 words here, one with one
test 1008.

The SKIP-shaped tests live in the NOP's hole, opcode 000 with bit 7 clear
and bits 6:0 not all 0, 4064 rejected words: bits 7:5 = 001 SKIP_SENT, 010
SKIP_RUN with bit 4 its sense, 011 SKIP_SAME, own operands in bits 3:0 as
SKIP's, a delay as any word, no side effect since SET owns the flag bit.
SHIFT_SENT is bit 0 of the SHIFT word, spare until now, bits 1:0 = 11.

The assembler keeps REPEAT's rules for a BRANCH as for a JMP: in a body it
lands in the body, from the label to the REPEAT; outside, it does not land
inside one past its label; a SKIP-shaped word is not a body's last word.

### Why C has two senses

The first C splice had `SKIP_RUN 5, 1` then `JMP stuff`, the baseline's
shape, `SKIP 0, 1` then `JMP dominant`, and stuffed after every bit that
did not end a run. A SKIP covers one case and the word after it is the
other: for a bit test the other case is the other level, so `SKIP 0, 1`
means "recessive: step over the dominant case". For a run test the other
case of "all five recessive" is not "all five dominant", it is "not all
five recessive", which no level says. So the SKIP shape needs the negated
test, SKIP_NORUN, and both senses cost the encoding 512 words each; the
BRANCH shape takes the run's side itself and needs one. This is the
SKIP-and-JMP asymmetry seen from the other end: SKIP's word after it is
the case SKIP does not cover, and a run test has no complementary level.

## What each does to the arbitration program

8 cycles a bit throughout; the bus the baseline's cycle for cycle in every
run, the same view from the receiver and the competitor, the same
outcome on every bit a loss can fall on.

| | baseline | A | B | Bc | AB | ABc |
|---|---|---|---|---|---|---|
| words | 95 | 84 | 95 | 84 | 84 | 73 |
| distinct words | 34 | 15 | 34 | 33 | 15 | 14 |
| words per identifier bit | 8 | 7 | 8 | 7 | 7 | 6 |
| pins on the bus side | 2, TXD and RXD | 2 | 1 | 1 | 1 | 1 |
| samples a bit | 2 | 2 | 2 | 1 | 2 | 1 |
| decision, cycles after the sample | 3 | 2 | 3 | 3 | 2 | 2 |
| the bus sampled, the level through the bit's | 4th (50%) | 5th (62.5%) | 4th | 4th | 5th | 5th |
| the decision reads | two samples | two samples | two samples | the pin register and a sample | two samples | the pin register and a sample |
| REPEAT | no | no | no | no | no | no |
| new state | | none | none | none | none | none |
| new words | | 1008 | 1152 | 256 | 2160 | 1768 |
| the host's byte | the last four (sent, seen) pairs, a loss (1, 0) last | the same | the same | the last eight bus samples: no sign of the loss | the same as the baseline | the last eight bus samples |
| cycles, won | 100 | 100 | 100 | 100 | 100 | 100 |
| cycles, lost on bit k | 8(k + 1) + 4, one more before ID[4] | one more | the same | the same | one more | one more |

Cell by cell: the baseline is `SHIFT_OUT`, `SHIFT_IN 0 [2]` (the sent
bit, TXD's readback), `SHIFT_IN 1` (the bus), `SKIP 1, 1`, `JMP next [1]`,
`SKIP 0, 0`, `JMP next`, `JMP lost`. A keeps the pins and puts `BRANCH 1,
0, pad`, `BRANCH 0, 1, next`, `JMP lost` and `pad: NOP` in place of the
four words: two cycles either way that goes on, the pad making the first
path as long as the second, and the saved cycle moves the bus sample a
clock later. B is the baseline word for word with `SHIFT_SENT 0` for the
readback and the pad back on the bus, `CONFIG open_drain01, 1`. Bc drops
the first sample, `SKIP_SENT 0, 1` reads the register in its place. ABc is
`SHIFT_OUT [4]`, `SHIFT_IN 0`, `BRANCH_SENT 0, 0, pad`, `BRANCH 0, 1,
next`, `JMP lost`, `pad: NOP`. The distinct-word counts say what a relative
branch does: A's eleven cells are the same seven words, 15 distinct for
34.

None of them gets a REPEAT body, and none can: the lost exit leaves the
loop, whatever word takes it (`test_arbitration_by_the_numbers`). So the
words do not collapse the way SWD's did: 95 to 73 at best, the cells still
written out. What the candidates change is the pins (B, Bc: one, as
`can_tx.asm` had), the decision (A: two cycles, symmetric, a later sample
point) and the words per bit (8 to 6). The 95-word explosion was the
unrolling first, and the unrolling is the exit's, not the decision's.

## What each does to the stuffing program

Each candidate at the shortest bit its decision fits in with the sample
point at 50% or later, the baseline's; then the same cell as a REPEAT body,
where the REPEAT's cycle and, where the stuff code sits inside the body, a
JMP over it come out of the sample point. The bus bit for bit the
baseline's in every form.

| | baseline | loop, today's ISA | A | A loop | C | C loop | AC | AC loop | D | D loop | AD | AD loop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| words | 224 | 91 | 168 | 74 | 104 | 46 | 97 | 46 | 104 | 46 | 97 | 46 |
| distinct words | 71 | 44 | 29 | 36 | 38 | 25 | 37 | 25 | 39 | 27 | 30 | 26 |
| words per checked bit | 27 | 27, a body | 20 | 22, a body | 12 | 12, a body | 4 + 7 out of line | 12, a body | 12 | 12, a body | 4 + 7 out of line | 12, a body |
| cycles a bit | 16 | 16 | 12 | 12 | **8** | **8** | **8** | **8** | 10 | 10 | **8** | **8** |
| the sample, the level through the bit's | 8th (50%) | 7th (43.75%) | 6th (50%) | 5th (41.7%) | 4th (50%) | 3rd (37.5%) | 5th (62.5%) | 3rd (37.5%) | 5th (50%) | 4th (40%) | 5th (62.5%) | 3rd (37.5%) |
| decision, cycles after the sample, every path | 7 | 8 | 5 | 6 | 3 | 4 | 2 | 4 | 4 | 5 | 2 | 4 |
| the decision is | a tree of SKIPs, exits padded | the same, to the REPEAT | a tree of BRANCHes into a ladder of NOPs | the same | two SKIP_NORUNs over JMPs, a JMP on | the same, to the REPEAT | two BRANCH_RUNs, the fall-through the next bit | the same, a JMP to the REPEAT | SKIP_SAME over a JMP, then SKIP 0 over a JMP | the same | BRANCH_SAME, then BRANCH 0 out of line, a NOP pad | the same |
| new state | | | none | | none | | none | | 3-bit counter, 1-bit last sample | | the same | |
| new words | | | 1008 | | 1024 | | 3040 | | 256 | | 2272 | |
| cycles, no stuff bit / two | 196 / 228 | 196 / 228 | 148 / 172 | 148 / 172 | 100 / 116 | 100 / 116 | 101 / 117 | 101 / 117 | 124 / 144 | 124 / 144 | 101 / 117 | 101 / 117 |

**16 cycles a bit to 8: yes.** C alone does it, no new state, the sample
at 50%, with a three-cycle decision: `SKIP_NORUN 5, 1`, `JMP dominant
[1]`, `SKIP_NORUN 5, 0`, `JMP recessive`, `JMP next`, the JMPs' delays
making the three paths the same length. AC and AD do it in two cycles and
put the sample at 62.5%, `BRANCH_RUN 5, 1, pad`, `BRANCH_RUN 5, 0,
recessive`, the fall-through being the next bit, which is why their stuff
code sits out of line after the exit (only a branch enters it; the exit
jumps past the end to halt, one cycle). A alone gets 12: the tree is still
five deep, the newest sample picking a side and four BRANCHes asking
whether the four before it match, but every exit lands on the same edge
through a ladder of three NOPs, so the padding is three words a cell
instead of a delay on every JMP. D alone gets 10: its decision is the
counter's test and then the level's, and the level's is a SKIP over a
JMP, so four cycles.

**The loop forms cost the sample point.** At 8 cycles a bit with the cell
a REPEAT body the sample falls on the third clock, 37.5%, for C, AC and
AD alike: the REPEAT is a cycle, and the stuff code inside the body has to
be jumped over on the path that stuffs nothing, another. AC's two-cycle
decision is worth nothing in a loop: the JMP and the REPEAT make it four,
the same as C's. A body that could be left early would give one cycle
back; that is the breakable loop the reviewer set aside, and it is not
built here, only measured.

**Words.** The checked bit is 27 words in the baseline, 20 with A, 12 with
C or D, 11 with AC or AD; with the cell a body, three of it and the ID[4]
cell written out with its PULL, 46 words for the whole frame in every
8-cycle form. The 224 to 91 is REPEAT's, on today's ISA; 91 to 46 is the
decision's.

## Encoding and state, side by side

| | where | new words | state | rules | cycles |
|---|---|---|---|---|---|
| A, BRANCH | opcode 110, bits 7:6 = 01, SKIP's rejected words | 1008 | none | as a JMP's in a REPEAT body; 1..63 ahead | 1, taken or not |
| B, SHIFT_SENT | SHIFT's spare bit 0 | 1152 | none | as SHIFT_IN's | 1 + delay |
| Bc, SKIP_SENT | the NOP hole, bits 7:5 = 001 | 256 | none | as SKIP's | 1 + delay |
| C, SKIP_RUN and SKIP_NORUN | the NOP hole, 010, bit 4 the sense | 1024 | none | as SKIP's | 1 + delay |
| D, SKIP_SAME | the NOP hole, 011 | 256 | 3-bit counter, 1-bit last sample, moved by every sample | as SKIP's; n at most 7 | 1 + delay |
| a second branch kind | kind 1 | 1008 more | | | |

In gates, on paper: A is a 6-bit add into the pc mux JMP already has and
a condition mux over the eight register bits, the same one SKIP has, gated
by the kind; C is a mask of the newest n bits under `shift_dir` and a
compare to the level replicated, no register; D is three bits, a compare
with the last sample and a saturating increment, and a compare against n;
B is a mux on SHIFT_IN's sample input; Bc a mux on SKIP's condition input.
Bc is the cheapest in gates and the only one that lets an output register
reach the pc: a program could use a spare pin as a one-bit flag.

## Where else each would serve

Measured where a program exists, otherwise by the shape.

| | A | B, Bc | C | D |
|---|---|---|---|---|
| SWD read, the ACK decision `SKIP 5, 0` then `JMP data` | one BRANCH: 102 words for 103, and the read with a target that says OK one cycle shorter, 378 for 379, the same bytes; the cycle that goes is one with SWCLK high, the JMP's: the OK path spent SKIP and JMP, two cycles, where WAIT and FAULT spent the SKIP alone. The asymmetry CAN measured was in SWD all along (`test_a_serves_swd_and_i2c_...`) | no: the host reads its own request back from the target, not from the pin | no | no |
| SWD, the WAIT retry `SKIP 6, 0` then `JMP request` | no: it goes back to word 1, and BRANCH goes ahead only; refused by the assembler | | | |
| I²C write, the ACK decision `SKIP 0, 0` then `JMP stop` | one BRANCH: 63 words for 64 | no | as SKIP, n = 1 | no |
| UART RX, a break or a framing check | a branch on the stop bit in one word | no | "the last n samples all 0" is a break; today it is n SKIPs | the same |
| any protocol that must know what it put out while seeing the line | | yes, from any pin; Bc as a flag register on a spare pin | | |

None of them touches an existing program: every program in `programs/`
assembles to the same words under every candidate and every word decodes
to the same instruction.

## What each disturbs

The existing model suite, 2772 tests with the two candidate files left
out, run on the candidate's model in the model's place. The copy of the
step with nothing added passes all 2772. What fails is the model of a word
the hardening suite pins, not a program: which words are rejected, what
bits 12:8 mean, what may reach the pc.

| | fails | what the failures are |
|---|---|---|
| A | 184 | 63 cases of "a delay only holds the state the first cycle produced": BRANCH's bits 12:8 are a condition; 16 random bodies with a BRANCH in them; 98 random programs whose new words are BRANCHes; 3 of "only WAIT and SKIP let an input reach the pc"; the word census, the side-effect field, the random walk |
| B | 57 | 53 random programs; the SHIFT opcode's in bit; the census, the side-effect field, the random walk |
| Bc | 63 | 54 random programs; 6 random bodies; the census, the side-effect field, the random walk |
| C | 99 | 78 random programs; 13 random bodies; 5 of "only WAIT and SKIP let an input reach the pc"; the census, the side-effect field, the random walk |
| D | 8 | 5 random programs; the census, the side-effect field, the random walk |
| AB | 207 | A's and B's |
| ABc | 218 | A's and Bc's |
| AC | 237 | A's and C's |
| AD | 165 | A's and D's |

Whichever is chosen, that model gets its clause, as REPEAT's did: one
more word whose bits 12:8 are not a delay and that moves the pc by more
than one (A); one more source that reaches the pc, the register or the pin
register (C, D, Bc); one more source for a sample (B).

## Findings

1. **The stuffing baseline overstated REPEAT's absence.** 224 words is
   91 on today's ISA with the cell a body. The stage 4 evidence that
   stands is the seven-cycle decision and the 16-cycle bit; the README's
   inventory is corrected.

2. **Stuffing comes back to 8 cycles a bit, and a run test is what does
   it**, with or without the branch. C alone: 3 cycles, 50%, no state. The
   branch on top makes the decision 2 cycles and the sample point 62.5%,
   and folds the stuff code out of line. A alone gets 12, D alone 10.

3. **The branch alone is worth measuring, and it measures the control
   flow's share.** Stuffing 224 to 168 words, 27 to 20 a bit, 16 to 12
   cycles a bit; arbitration 95 to 84 with 15 distinct words for 34. The
   rest of the stuffing explosion is the five-bit question (168 to 97), and
   the rest of arbitration's is the exit (84 stays 84 until the pin goes,
   73 with both).

4. **The arbitration words do not collapse.** No candidate here can fold
   the eleven cells, because the lost exit leaves any body, and a body
   that can be left is what the reviewer set aside. B answers the question
   asked of it: one bit of output history, exposed, puts the pad back on
   the bus with the baseline's 95 words unchanged; Bc does it without the
   second sample and takes the loss out of the host's byte.

5. **A run test in SKIP form needs both senses**, because the word after a
   SKIP is the case the SKIP does not cover and a run's other case is not
   a level; in BRANCH form it needs one. That is the asymmetry the two
   complaints share, seen from the encoding.

6. **D is dominated by C.** The same decision depth, since the level
   still has to be asked, one cycle more in SKIP form, four flops and a
   compare, and n at most 7. What it would offer, a run longer than the
   register, CAN does not ask for.

7. **A relative, forward-only branch reaches every CAN cell and not
   SWD's retry.** 63 ahead is enough here, not with a wide margin: the
   longest is 56, ID[7]'s branch to its stuff code, which sits after every
   cell and the exit; the retry goes back 30 words. A backward reach would
   cost a sign bit, 31 either way, or the delay field's trick.

8. **The loop forms show what REPEAT costs a decision**: a cycle for the
   REPEAT and one for the JMP over the stuff code, two clocks of sample
   point at 8 cycles a bit. AC's two-cycle decision is four in a loop.
   Not fixed: the breakable loop is a separate question, as the reviewer
   said.

9. **The SWD read had the asymmetry too**: its OK path was a cycle longer
   than its WAIT path, SWCLK high, and nobody noticed because SWD's target
   waits for the clock. CAN's bit does not wait, which is why it showed.

10. **Everything here takes rejected words only.** The branch family in
    SKIP's opcode, the SKIP-shaped tests in the NOP's hole, the sent bit in
    SHIFT's spare bit; no valid word changes meaning, and every program in
    `programs/` means the same under every candidate.

## Not decided

The reviewer's call, after this: whether the branch earns its word, which
of the run tests, whether the sent bit is a sample or a condition; and
CRC stays separate, its arithmetic pressure not to be mixed with these.
Nothing in the core is touched; the 95- and 224-word programs are the
record of why.

## Files

- `experiments/can/candidates.py`: the models; `Candidate` is cpu.CPU's step written out with hooks, REPEAT included
- `experiments/can/gen.py`: writes every splice below, the cycles counted in the comments
- `experiments/can/can_tx_arb_{A,B,Bc,AB,ABc}.asm`: arbitration, 8 cycles a bit
- `experiments/can/can_tx_stuff_loop.asm`: today's ISA, the cell a REPEAT body: the correction
- `experiments/can/can_tx_stuff_{A,C,AC,D,AD}.asm` and `_loop`: stuffing, written out and as bodies
- `experiments/can/plugin.py`, `suite.py`: the existing suite on a candidate's model
- `tests/test_can_candidates.py`: the comparison, pinned, on the candidates' models
