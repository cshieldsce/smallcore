# can_tx_stuff.asm with SKIP_NORUN: the SOF and the 11-bit identifier with
# dynamic bit stuffing, the pad on the bus, 8 cycles a bit, driven on the
# first and sampled on the 4th (the level through the 3rd, 37.5%). The
# decision is two run tests: five recessive? five dominant? each a SKIP_NORUN
# over the JMP to its stuff bit, the no-run path's JMP to the next bit: three
# cycles on every path after the sample. The SKIP is the negated test: the
# word after a SKIP is the case it does not cover, and a run's other case is
# not a level. ID[7], ID[6], ID[5] one REPEAT body, ID[3] to ID[0] another,
# ID[4] with its PULL written out between them in the unrolled cell's shape;
# the REPEAT's cycle and the JMP over the stuff code are paid for by sampling
# earlier. The host writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for
# can_tx.asm and reads the last eight samples, stuff bits among them. 46
# words, 25 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [2]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 3
        SHIFT_IN 0 [3]          # sampled on the 4th, held 4, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [2]           # ID7: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id7d [2]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id7r [1]            # five dominant: a recessive stuff bit on the ninth
        JMP end1                # no run: the REPEAT on the eighth
id7d:   SET 0, 0 [3]            # the stuff bit, dominant
        SHIFT_IN 0 [1]
        JMP end1
id7r:   SET 0, 1 [3]            # the stuff bit, recessive
        SHIFT_IN 0 [2]          # the REPEAT follows
end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]
id4:    SHIFT_OUT [2]           # ID4: driven, held three, and
        PULL                    # {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id4d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id4r                # five dominant: a recessive stuff bit on the ninth
        JMP id3                 # no run: the next bit on the ninth
id4d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id3                 # the eighth: the next bit
id4r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id3:    SHIFT_OUT [2]           # ID3: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id3d [2]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id3r [1]            # five dominant: a recessive stuff bit on the ninth
        JMP end2                # no run: the REPEAT on the eighth
id3d:   SET 0, 0 [3]            # the stuff bit, dominant
        SHIFT_IN 0 [1]
        JMP end2
id3r:   SET 0, 1 [3]            # the stuff bit, recessive
        SHIFT_IN 0 [2]          # the REPEAT follows
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
