# can_tx_stuff.asm with BRANCH_RUN: the SOF and the 11-bit identifier with
# dynamic bit stuffing, the pad on the bus, 8 cycles a bit, driven on the
# first and sampled on the 6th (the level through the 5th, 62.5%). The
# decision is two run tests, five recessive? five dominant? each a BRANCH_RUN
# to its stuff bit, the fall-through the next bit: two cycles on every path
# after the sample, the stuff code out of line. Every checked bit written out,
# ID[7] to ID[0]: a run of five cannot end before ID[7]. The stuff code sits
# after the exit, which jumps past the end to halt, since only a branch enters
# it. The host writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm
# and reads the last eight samples, stuff bits among them. 97 words,
# 37 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [4]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 5
        SHIFT_IN 0 [1]          # sampled on the 6th, held 2, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [4]           # ID7: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id7p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id7r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id6:    SHIFT_OUT [4]           # ID6: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id6p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id6r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id5:    SHIFT_OUT [4]           # ID5: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id5p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id5r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id4:    SHIFT_OUT [3]           # ID4: driven, held four, and
        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id4p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id4r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id3:    SHIFT_OUT [4]           # ID3: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id3p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id3r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id2:    SHIFT_OUT [4]           # ID2: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id2p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id2r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id1:    SHIFT_OUT [4]           # ID1: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id1p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id1r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id0:    SHIFT_OUT [4]           # ID0: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id0p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id0r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
        JMP halt                # past the end: halted; the stuff code below is entered by branch only
id7p:   NOP                     # ID7's stuff bits: the pad, then
id7d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id6                 # the eighth: the next bit
id7r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id6
id6p:   NOP                     # ID6's stuff bits: the pad, then
id6d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id5                 # the eighth: the next bit
id6r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id5
id5p:   NOP                     # ID5's stuff bits: the pad, then
id5d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id4                 # the eighth: the next bit
id5r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id4
id4p:   NOP                     # ID4's stuff bits: the pad, then
id4d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id3                 # the eighth: the next bit
id4r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id3
id3p:   NOP                     # ID3's stuff bits: the pad, then
id3d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id2                 # the eighth: the next bit
id3r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id2
id2p:   NOP                     # ID2's stuff bits: the pad, then
id2d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id1                 # the eighth: the next bit
id2r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id1
id1p:   NOP                     # ID1's stuff bits: the pad, then
id1d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id0                 # the eighth: the next bit
id1r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id0
id0p:   NOP                     # ID0's stuff bits: the pad, then
id0d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP done                # the eighth: the next bit
id0r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP done
halt:
