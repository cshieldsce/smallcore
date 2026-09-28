# can_tx_arb.asm with SHIFT_SENT: the SOF and the 11-bit identifier under
# arbitration, 8 cycles a bit, the pad on the bus, one pin. Per bit: the bit
# driven on the first cycle, its register sampled on the second by SHIFT_SENT,
# the bus on the fifth, then the baseline's SKIP, JMP, SKIP, JMP, three cycles
# on every path; the words are the baseline's with SHIFT_SENT 0 for SHIFT_IN 0
# and SHIFT_IN 0 for SHIFT_IN 1. The exits are the baseline's: lost1 takes the
# stranded second byte, lost lets go and hands the host the last four (sent,
# seen) pairs, a loss (1, 0) last. 95 words, 34 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
        SHIFT_OUT [7]           # SOF: dominant, every node's; nothing to decide

id10:   SHIFT_OUT               # ID10: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id9 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id9                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id9:    SHIFT_OUT               # ID9: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id8 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id8                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id8:    SHIFT_OUT               # ID8: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id7 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id7                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id7:    SHIFT_OUT               # ID7: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id6 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id6                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id6:    SHIFT_OUT               # ID6: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id5 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id5                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id5:    SHIFT_OUT               # ID5: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id4 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id4                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id4:    SHIFT_OUT               # ID4: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [1]        # the bit as sent: the register behind the pad, and
        PULL                    # {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id3 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id3                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id3:    SHIFT_OUT               # ID3: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id2 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id2                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id2:    SHIFT_OUT               # ID2: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id1 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id1                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id1:    SHIFT_OUT               # ID1: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP id0 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id0                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id0:    SHIFT_OUT               # ID0: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_SENT 0 [2]        # the bit as sent: the register behind the pad
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP 1, 1               # sent recessive? step over the JMP
        JMP lost [1]            # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP lost                # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
lost1:  PULL                    # lost before ID[4]'s PULL: {ID[3:0], 0000} is still queued; take it and drop it
lost:   PUSH 0, 1               # let go, as a loss already has; the byte to the host
