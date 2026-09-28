# can_tx_arb.asm with SKIP_SENT: the SOF and the 11-bit identifier under
# arbitration, 8 cycles a bit, the pad on the bus, one pin. Per bit: the bit
# driven on the first cycle, the bus sampled on the fifth, then SKIP_SENT on
# the register behind the pad, JMP, SKIP on the sample, JMP: the baseline's
# decision without its first sample. The exits are the baseline's: lost1 takes
# the stranded second byte, lost lets go and hands the host the last eight bus
# samples, in which a loss does not show. 84 words, 33 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
        SHIFT_OUT [7]           # SOF: dominant, every node's; nothing to decide

id10:   SHIFT_OUT [3]           # ID10: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id9 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id9                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id9:    SHIFT_OUT [3]           # ID9: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id8 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id8                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id8:    SHIFT_OUT [3]           # ID8: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id7 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id7                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id7:    SHIFT_OUT [3]           # ID7: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id6 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id6                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id6:    SHIFT_OUT [3]           # ID6: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id5 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id5                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id5:    SHIFT_OUT [3]           # ID5: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id4 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id4                 # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
id4:    SHIFT_OUT [2]           # ID4: the bit, and
        PULL                    # {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id3 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id3                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id3:    SHIFT_OUT [3]           # ID3: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id2 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id2                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id2:    SHIFT_OUT [3]           # ID2: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id1 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id1                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id1:    SHIFT_OUT [3]           # ID1: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP id0 [1]             # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP id0                 # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
id0:    SHIFT_OUT [3]           # ID0: the bit, a 0 pulls the bus dominant, a 1 lets go
        SHIFT_IN 0              # the bus, the fifth cycle
        SKIP_SENT 0, 1          # sent recessive? step over the JMP
        JMP lost [1]            # sent dominant: nothing to lose
        SKIP 0, 0               # saw dominant? step over the JMP
        JMP lost                # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
lost1:  PULL                    # lost before ID[4]'s PULL: {ID[3:0], 0000} is still queued; take it and drop it
lost:   PUSH 0, 1               # let go, as a loss already has; the byte to the host
