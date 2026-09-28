# can_tx_arb.asm with BRANCH: the SOF and the 11-bit identifier under
# arbitration, 8 cycles a bit, the transceiver's view: TXD on pin 0, its
# readback on gpio_in 0, the bus on gpio_in 1. Per bit: TXD driven on the
# first cycle, the sent bit sampled on the second, the bus on the sixth (the
# level through the fifth, 62.5%), then BRANCH sent dominant -> a pad, BRANCH
# seen recessive -> the next bit, else JMP lost: two cycles on every path that
# goes on, the pad's NOP making the first as long as the second. The exits are
# the baseline's: lost1 takes the stranded second byte, lost lets go and hands
# the host the last four (sent, seen) pairs, a loss (1, 0) last. 84
# words, 15 distinct.

        CONFIG open_drain01, 2  # RXD, pin 1, is a pad we listen on: open-drain, its reset 1 lets go; TXD, pin 0, stays push-pull
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
        SHIFT_OUT [7]           # SOF: dominant, every node's; nothing to decide

id10:   SHIFT_OUT               # ID10: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p10        # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id9        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p10:    NOP
id9:    SHIFT_OUT               # ID9: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p9         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id8        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p9:     NOP
id8:    SHIFT_OUT               # ID8: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p8         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id7        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p8:     NOP
id7:    SHIFT_OUT               # ID7: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p7         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id6        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p7:     NOP
id6:    SHIFT_OUT               # ID6: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p6         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id5        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p6:     NOP
id5:    SHIFT_OUT               # ID5: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p5         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id4        # saw recessive: still in
        JMP lost1               # sent recessive, saw dominant: lost
p5:     NOP
id4:    SHIFT_OUT               # ID4: TXD = the bit
        SHIFT_IN 0 [2]          # the bit as sent, TXD read back, and
        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p4         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id3        # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
p4:     NOP
id3:    SHIFT_OUT               # ID3: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p3         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id2        # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
p3:     NOP
id2:    SHIFT_OUT               # ID2: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p2         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id1        # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
p2:     NOP
id1:    SHIFT_OUT               # ID1: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p1         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, id0        # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
p1:     NOP
id0:    SHIFT_OUT               # ID0: TXD = the bit
        SHIFT_IN 0 [3]          # the bit as sent, TXD read back
        SHIFT_IN 1              # the bus, the sixth cycle
        BRANCH 1, 0, p0         # sent dominant: nothing to lose, the pad then the next bit
        BRANCH 0, 1, lost       # saw recessive: still in
        JMP lost                # sent recessive, saw dominant: lost
p0:     JMP lost
lost1:  PULL                    # lost before ID[4]'s PULL: {ID[3:0], 0000} is still queued; take it and drop it
lost:   PUSH 0, 1               # let go, as a loss already has; the byte to the host
