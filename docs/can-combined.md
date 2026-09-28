# The combined CAN programs

**Outcome (2026-09-28): the unopposed frame fits, arbitration fits only
with the identifier in the program, and the receiver meets the three-stream
wall, as expected.** This is the payoff test for the run test and the
accumulator: a whole Classical CAN frame on the ISA as it is, in 256 words,
at 8 clocks a bit. Nothing in the ISA or the RTL changes here. The programs
are written by `experiments/combined/gen.py`, pinned on the model by
`tests/test_can_combined.py`, and run at the pins by `rtl_tests/top_tb.py`.

## The cell

Every checked bit is one cell, 8 cycles on the path that stuffs nothing and
16 on a path that stuffs:

```
  b1..b3   the bit onto the pad, and the words that ride before the sample:
           ACC_CRC on the pad on b3 for a data bit, the PULL in a body's
           first cell, or ACC_OUT for a CRC bit, which is the bit
  b4       SHIFT_IN: the level through the third clock, 37.5%
  b5..b8   SKIP_NORUN 5, 1 and SKIP_NORUN 5, 0 over their JMPs, a JMP on
  b9..b16  the stuff bit, SET, sampled on its fourth clock as every bit
```

The CRC reads the pad on b3, the level through the second clock. It first
read on b2, the first clock's level, and the combined bench broke it twice.
A one-clock probe showed the CRC changing for a pulse on the bit's first
clock. A rival that syncs on the SOF's edge, a clock behind, broke the
winner's CRC with the one clock its withdrawn dominant bit overlapped. The
CRC's sample needs a settled bus, like any other sample.

## By the numbers

| | 6A, unopposed | 6B, arbitration | 6C, the receiver |
|---|---|---|---|
| program | `can_tx_combined.asm` | `can_tx_arb_<ident>.asm`, one per identifier | `can_rx_crc.asm` |
| words | **152**, 64 distinct | **206 to 228** over all 2048 identifiers; 214 for 0x5A3 | **35**, 25 distinct |
| clocks a bit | 8 | 8 | 8 |
| the CRC | the core's, `ACC_CRC` then `ACC_OUT`, stuffed | the core's | checked in the core: the residue, 0 when it matched |
| the host writes | the polynomial once, then 3 + DLC bytes a frame, no CRC | the polynomial once, then DLC + 1 bytes | the polynomial once |
| the host reads | {the last seven samples, ACK} | the same when won; two bytes when lost | 42 bytes a frame, the stream a bit a byte, and the residue in 2 |
| the host may sleep | not measured | not measured | 4 bit times |
| against | stage 5A: 233 words, 16 clocks a bit, the CRC the host's | can_tx_arb.asm: the identifier only, a transceiver's two pins | can_rx_bits_C.asm: 27 words, no CRC |

For DLC 1, as every CAN program here. A payload length is the body's REPEAT
count, one word.

## 6A: the whole frame unopposed

Stage 5A's frame with the run test and the accumulator. It is the same
eight-cell body with the PULL in the first cell, run 2 + DLC times, and the
last data bit a cell of its own. The CRC is a one-cell body run fifteen
times, `ACC_OUT 0` on b1, sampled and stuffed as every bit. acc is clear
after the fifteenth, ready for the next frame. The host writes no CRC. The
fixed form after the CRC is stage 5A's at 8 clocks a bit. Not acked, the
program goes round for the host's next frame and keeps the polynomial.

**152 words at 8 clocks a bit, for 233 at 16.** The run test halved the bit
and the cell. The accumulator took the CRC off the host and put it on the
wire from the core. On the frames, the walking ones and zeros and every
97th identifier, the receiver finds the CRC right and acks.

## 6B: arbitration

Arbitration asks a node for the bit it sent beside the bit on the bus.
Stuffing asks for the last five bus bits. Both sit in the one register that
SKIP and the run test read. Two samples a bit leave four bits of history in
eight, and the run test needs five. With the identifier from the host the
transmitter has three streams: the sent bit, the history and the CRC.
`in_shift_reg` and `acc` are two places. This is arithmetic on the
register's width, not a built program: the TX side of the wall RX met.

What fits is **the identifier in the program**. The header, SOF, ID, RTR,
IDE, r0 and the DLC, is written out bit by bit with its stuff bits, which
the assembler knows. The comparison is then the assembler's too:

- **A recessive bit** is `SET 0, 1`, `ACC_CRC 0`, `SHIFT_IN 0` and `SKIP
  0, 1 [3]` over `JMP lost`. It checks the bus.
- **A dominant bit** is `SET 0, 0`, `ACC_CRC 0` and `SHIFT_IN 0 [4]`. It
  cannot lose.
- **Every sample goes into the register**, so the run test is right when
  the data starts.

The pad is on the bus, open-drain, one pin: no transceiver view is needed,
because the program knows what it sent. The data and the CRC are 6A's.
Lost, the pad lets go on the losing bit and never drives again. The host
reads two bytes and the program halts, where a won frame hands it one.

**Every identifier fits: 206 to 228 words.** A recessive header bit costs
five words, a dominant one three, a stuff bit two or four. The price is one
program per identifier and DLC. A node sends a handful of identifiers, and
the ROM has slots, but it is a price: the identifier is no longer the
host's byte.

Held to a Rival that stuffs, syncs on the SOF a clock behind and withdraws
the way a node must, on four identifiers:

- **A lower rival on each recessive bit wins.** Its frame reaches the
  receiver whole, CRC right. The transmitter's pad is off the bus from the
  losing bit on.
- **A higher rival on each dominant bit withdraws**, and the transmitter's
  frame is received and acked.

## 6C: the receiver

Three streams, two places, deliberately:

- **The raw history is in `in_shift_reg`**, for the run test.
- **The CRC is in `acc`.** `ACC_CRC 0` runs on b2, the clock after the data
  sample, and stuff bits are left out.
- **The data leaves one bit a byte through the FIFO**, a PUSH on b3, as in
  `can_rx_bits_C.asm`, because there is nowhere else to put it.

The CRC runs over the whole destuffed stream, the frame's CRC included, so
the residue is 0 when the CRC matched. Two `ACC_PUSH`es hand it to the host
after the intermission. 35 words at 8 clocks a bit. The host pops 44 bytes
a frame and may sleep four bit times.

The other assignment is `experiments/acc/can_rx_bytes.asm`: the data bytes
in acc and the CRC left to the host, 92 words, 6 bytes a frame, 33 bit
times of slack. **Neither gives the host bytes and the core the CRC at
once.** The handoff at a useful boundary is the byte, and the byte needs
the second register the CRC is using.

**The ACK cannot depend on the CRC.** A receiver acks a frame only when its
CRC matched. This one pulls the slot whatever the residue says, and the
bench pins that: a wrong CRC leaves a residue and is acked all the same.
The residue is in acc, and nothing takes a bit of acc to the pc but a pin
and a sample. Fifteen bits at two cycles each is thirty cycles, and the CRC
delimiter leaves eight before the slot. A new pressure, not fixed: a
decision on acc.

## Findings

1. **The payoff holds for the unopposed frame.** The whole data frame, the
   CRC the core's, is 152 words at 8 clocks a bit. The run test and the
   accumulator together took stage 5A's 233 words at 16 clocks and a host
   CRC to that.

2. **Arbitration is the transmitter's third stream.** The sent bit, the
   five-bit history and the CRC do not fit the two places. The identifier
   in the program makes the comparison static and fits every identifier in
   228 words at most, at one program per identifier. A dynamic identifier
   under arbitration with stuffing at 8 clocks a bit is not possible on
   this ISA, by the register's width.

3. **The receiver has the same wall.** The raw history, the data and the
   CRC want three places. Measured both ways: the CRC in the core and the
   data a bit a byte, 35 words and a host at four bit times; or the data in
   bytes and the CRC the host's, 92 words and 33 bit times.

4. **A decision on acc is missing.** The receiver's conditional ACK needs
   "was the residue 0?" before the slot, and acc reaches the pc only
   through a pin a bit at a time. The accumulator is a second stream the
   pc cannot see.

5. **The CRC's sample point matters.** The first placement read the bus's
   first clock. A probe and a late rival both found it. It reads the second
   now.

## Files

- `experiments/combined/gen.py`: writes every program below
- `experiments/combined/can_tx_combined.asm`: 6A, 152 words
- `experiments/combined/can_tx_arb_{5a3,7ff,000}.asm`: 6B for three identifiers; the tests generate the rest
- `experiments/combined/can_rx_crc.asm`: 6C, 35 words
- `tests/test_can_combined.py`: the frames, the rivals, the probe, every identifier's size, the receiver's residue and its ACK
- `rtl_tests/top_tb.py`: `can_frame_with_the_crc_in_the_core_at_the_pins`, `can_arbitrating_frame_at_the_pins`, `can_receiver_with_the_crc_in_the_core_at_the_pins`
