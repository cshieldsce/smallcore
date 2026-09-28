# can_tx_stuff.asm with BRANCH_SAME, the run counter: the SOF and the 11-bit
# identifier with dynamic bit stuffing, the pad on the bus, 8 cycles a bit,
# driven on the first and sampled on the 6th (the level through the 5th,
# 62.5%). The decision is the counter's test, five the same? a BRANCH_SAME to
# the stuff code out of line, where a BRANCH on the newest bit picks the
# level; a NOP pads the no-run path: two cycles on every path. Every checked
# bit written out, ID[7] to ID[0]: a run of five cannot end before ID[7]. The
# stuff code sits after the exit, which jumps past the end to halt, since only
# a branch enters it. The host writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as
# for can_tx.asm and reads the last eight samples, stuff bits among them.
# 97 words, 30 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [4]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 5
        SHIFT_IN 0 [1]          # sampled on the 6th, held 2, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [4]           # ID7: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id7s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id6:    SHIFT_OUT [4]           # ID6: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id6s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id5:    SHIFT_OUT [4]           # ID5: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id5s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id4:    SHIFT_OUT [3]           # ID4: driven, held four, and
        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id4s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id3:    SHIFT_OUT [4]           # ID3: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id3s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id2:    SHIFT_OUT [4]           # ID2: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id2s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id1:    SHIFT_OUT [4]           # ID1: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id1s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id0:    SHIFT_OUT [4]           # ID0: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_SAME 5, id0s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
        JMP halt                # past the end: halted; the stuff code below is entered by branch only
id7s:   BRANCH 0, 0, id7r       # ID7's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id6                 # the eighth: the next bit
id7r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id6
id6s:   BRANCH 0, 0, id6r       # ID6's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id5                 # the eighth: the next bit
id6r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id5
id5s:   BRANCH 0, 0, id5r       # ID5's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id4                 # the eighth: the next bit
id5r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id4
id4s:   BRANCH 0, 0, id4r       # ID4's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id3                 # the eighth: the next bit
id4r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id3
id3s:   BRANCH 0, 0, id3r       # ID3's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id2                 # the eighth: the next bit
id3r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id2
id2s:   BRANCH 0, 0, id2r       # ID2's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id1                 # the eighth: the next bit
id2r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id1
id1s:   BRANCH 0, 0, id1r       # ID1's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id0                 # the eighth: the next bit
id1r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id0
id0s:   BRANCH 0, 0, id0r       # ID0's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP done                # the eighth: the next bit
id0r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP done
halt:
