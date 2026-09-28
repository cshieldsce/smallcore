# can_tx_stuff.asm with BRANCH_SAME, the run counter: the SOF and the 11-bit
# identifier with dynamic bit stuffing, the pad on the bus, 8 cycles a bit,
# driven on the first and sampled on the 4th (the level through the 3rd,
# 37.5%). The decision is the counter's test, five the same? a BRANCH_SAME to
# the stuff code out of line, where a BRANCH on the newest bit picks the
# level; a NOP pads the no-run path: two cycles on every path. ID[7], ID[6],
# ID[5] one REPEAT body, ID[3] to ID[0] another, ID[4] with its PULL written
# out between them in the unrolled cell's shape; the REPEAT's cycle and the
# JMP over the stuff code are paid for by sampling earlier. The host writes
# {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm and reads the last
# eight samples, stuff bits among them. 46 words, 26 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [2]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 3
        SHIFT_IN 0 [3]          # sampled on the 4th, held 4, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [2]           # ID7: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        BRANCH_SAME 5, id7s     # five the same: a stuff bit, which level to decide
        JMP end1 [1]            # no run: the REPEAT on the eighth
id7s:   BRANCH 0, 0, id7r       # dominant run? a recessive stuff bit
        NOP [1]                 # the dominant stuff bit on the ninth
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
        BRANCH_SAME 5, id4s     # five the same: a stuff bit, which level to decide
        NOP                     # no run: the next bit follows, on the ninth
id3:    SHIFT_OUT [2]           # ID3: driven, held three
        SHIFT_IN 0              # sampled on the fourth
        BRANCH_SAME 5, id3s     # five the same: a stuff bit, which level to decide
        JMP end2 [1]            # no run: the REPEAT on the eighth
id3s:   BRANCH 0, 0, id3r       # dominant run? a recessive stuff bit
        NOP [1]                 # the dominant stuff bit on the ninth
        SET 0, 0 [4]
        SHIFT_IN 0
        JMP end2
id3r:   NOP [1]                 # the recessive stuff bit on the ninth
        SET 0, 1 [4]
        SHIFT_IN 0 [1]          # the REPEAT follows
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
        JMP halt                # past the end: halted; the stuff code below is entered by branch only
id4s:   BRANCH 0, 0, id4r       # ID4's stuff bits: dominant run? a recessive stuff bit
        SET 0, 0 [4]            # the dominant stuff bit, driven, held five, on the ninth
        SHIFT_IN 0 [1]          # sampled on its sixth like every bit, held two, and
        JMP id3                 # the eighth: the next bit
id4r:   SET 0, 1 [4]            # the recessive stuff bit, let go, held five
        SHIFT_IN 0 [1]
        JMP id3
halt:
