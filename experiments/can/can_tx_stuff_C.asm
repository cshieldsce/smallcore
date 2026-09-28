# can_tx_stuff.asm with SKIP_NORUN: the SOF and the 11-bit identifier with
# dynamic bit stuffing, the pad on the bus, 8 cycles a bit, driven on the
# first and sampled on the 5th (the level through the 4th, 50%). The decision
# is two run tests: five recessive? five dominant? each a SKIP_NORUN over the
# JMP to its stuff bit, the no-run path's JMP to the next bit: three cycles on
# every path after the sample. The SKIP is the negated test: the word after a
# SKIP is the case it does not cover, and a run's other case is not a level.
# Every checked bit written out, ID[7] to ID[0]: a run of five cannot end
# before ID[7]. The host writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for
# can_tx.asm and reads the last eight samples, stuff bits among them. 104
# words, 38 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [3]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 4
        SHIFT_IN 0 [2]          # sampled on the 5th, held 3, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [3]           # ID7: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id7d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id7r                # five dominant: a recessive stuff bit on the ninth
        JMP id6                 # no run: the next bit on the ninth
id7d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id6                 # the eighth: the next bit
id7r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id6:    SHIFT_OUT [3]           # ID6: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id6d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id6r                # five dominant: a recessive stuff bit on the ninth
        JMP id5                 # no run: the next bit on the ninth
id6d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id5                 # the eighth: the next bit
id6r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id5:    SHIFT_OUT [3]           # ID5: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id5d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id5r                # five dominant: a recessive stuff bit on the ninth
        JMP id4                 # no run: the next bit on the ninth
id5d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id4                 # the eighth: the next bit
id5r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
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
id3:    SHIFT_OUT [3]           # ID3: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id3d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id3r                # five dominant: a recessive stuff bit on the ninth
        JMP id2                 # no run: the next bit on the ninth
id3d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id2                 # the eighth: the next bit
id3r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id2:    SHIFT_OUT [3]           # ID2: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id2d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id2r                # five dominant: a recessive stuff bit on the ninth
        JMP id1                 # no run: the next bit on the ninth
id2d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id1                 # the eighth: the next bit
id2r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id1:    SHIFT_OUT [3]           # ID1: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id1d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id1r                # five dominant: a recessive stuff bit on the ninth
        JMP id0                 # no run: the next bit on the ninth
id1d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP id0                 # the eighth: the next bit
id1r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
id0:    SHIFT_OUT [3]           # ID0: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_NORUN 5, 1         # five recessive? no: step over the JMP
        JMP id0d [1]            # five recessive: a dominant stuff bit on the ninth
        SKIP_NORUN 5, 0         # five dominant? no: step over the JMP
        JMP id0r                # five dominant: a recessive stuff bit on the ninth
        JMP done                # no run: the next bit on the ninth
id0d:   SET 0, 0 [3]            # the stuff bit, dominant, driven, held four
        SHIFT_IN 0 [2]          # sampled on its fifth like every bit, held three, and
        JMP done                # the eighth: the next bit
id0r:   SET 0, 1 [3]            # the stuff bit, recessive, let go, held four
        SHIFT_IN 0 [3]          # sampled on its fifth, held four: the next bit follows
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
