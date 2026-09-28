# can_tx_stuff.asm with BRANCH_RUN: the SOF and the 11-bit identifier with
# dynamic bit stuffing, the pad on the bus, 8 cycles a bit, driven on the
# first and sampled on the 4th (the level through the 3rd, 37.5%). The
# decision is two run tests, five recessive? five dominant? each a BRANCH_RUN
# to its stuff bit, the fall-through the next bit: two cycles on every path
# after the sample, the stuff code out of line. ID[7], ID[6], ID[5] one REPEAT
# body, ID[3] to ID[0] another, ID[4] with its PULL written out between them
# in the unrolled cell's shape; the REPEAT's cycle and the JMP over the stuff
# code are paid for by sampling earlier. The host writes {SOF 0, ID[10:4]} and
# {ID[3:0], 0000} as for can_tx.asm and reads the last eight samples, stuff
# bits among them. 46 words, 25 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [2]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 3
        SHIFT_IN 0 [3]          # sampled on the 4th, held 4, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [2]           # ID7: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        BRANCH_RUN 5, 1, id7p   # five recessive: a dominant stuff bit
        BRANCH_RUN 5, 0, id7r   # five dominant: a recessive stuff bit
        JMP end1                # no run: the REPEAT on the eighth
id7p:   NOP [2]                 # the dominant stuff bit on the ninth
        SET 0, 0 [4]
        SHIFT_IN 0
        JMP end1
id7r:   NOP [1]                 # the recessive stuff bit on the ninth
        SET 0, 1 [4]
        SHIFT_IN 0 [1]          # the REPEAT follows
end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]
id4:    SHIFT_OUT [3]           # ID4: driven, held four, and
        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the sixth
        BRANCH_RUN 5, 1, id4p   # five recessive: a dominant stuff bit, a pad's cycle first
        BRANCH_RUN 5, 0, id4r   # five dominant: a recessive stuff bit on the ninth; no run: the next bit follows
id3:    SHIFT_OUT [2]           # ID3: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        BRANCH_RUN 5, 1, id3p   # five recessive: a dominant stuff bit
        BRANCH_RUN 5, 0, id3r   # five dominant: a recessive stuff bit
        JMP end2                # no run: the REPEAT on the eighth
id3p:   NOP [2]                 # the dominant stuff bit on the ninth
        SET 0, 0 [4]
        SHIFT_IN 0
        JMP end2
id3r:   NOP [1]                 # the recessive stuff bit on the ninth
        SET 0, 1 [4]
        SHIFT_IN 0 [1]          # the REPEAT follows
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
        JMP halt                # past the end: halted; the stuff code below is entered by branch only
id4p:   NOP                     # ID4's stuff bits: the pad, then
id4d:   SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id3                 # the eighth: the next bit
id4r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id3
halt:
