# CAN transmitter, stage 2: the SOF and the 11-bit identifier under
# arbitration, a second transmitter on the bus. A node that sends recessive
# and sees dominant has lost and must send nothing more. With the pad on the
# bus (can_tx.asm) the core cannot tell that bit from its own dominant one: the
# sent bit sits on the pin register, which nothing reads. So this program sees
# the bus the way a controller behind a transceiver does: gpio 0 is TXD,
# push-pull, and gpio_in 0, its pad readback, is the bit as sent; gpio_in 1 is
# RXD, the bus, pin 1 let go. A bit is 8 cycles: TXD driven on the first, the
# sent bit sampled on the second, the bus on the fifth, the level it held
# through its fourth (50%: the decision needs the three cycles after it), then
# the pair decides, SKIP, JMP, SKIP, JMP, three cycles on every path, JMP lost
# to the exit on (1, 0). A JMP out of a body is what REPEAT forbids, so the
# eleven identifier cells are written out, 8 words each. Lost or through, the
# exit is one word: TXD recessive, as it already is on a loss, and the last
# four (sent, seen) pairs to the host, who reads a loss as (1, 0) last. A loss
# before ID[4]'s PULL leaves the second byte in the TX FIFO, and only a PULL
# can drop it, so those cells exit through one. The host writes {SOF 0,
# ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm. 95 words, 34 distinct.

        CONFIG open_drain01, 2  # RXD, pin 1, is a pad we listen on: open-drain, its reset 1 lets go; TXD, pin 0, stays push-pull
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
        SHIFT_OUT [7]           # SOF: dominant, every node's; nothing to decide

        SHIFT_OUT               # ID[10]: TXD = the bit
        SHIFT_IN 0 [2]          #         the bit as sent, TXD read back
        SHIFT_IN 1              #         the bus, the fifth cycle
        SKIP 1, 1               #         sent recessive? step over the JMP
        JMP id9 [1]             #         sent dominant: nothing to lose
        SKIP 0, 0               #         saw dominant? step over the JMP
        JMP id9                 #         saw recessive: still in
        JMP lost1               #         sent recessive, saw dominant: lost, the second byte still queued
id9:    SHIFT_OUT               # ID[9]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id8 [1]
        SKIP 0, 0
        JMP id8
        JMP lost1
id8:    SHIFT_OUT               # ID[8]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id7 [1]
        SKIP 0, 0
        JMP id7
        JMP lost1
id7:    SHIFT_OUT               # ID[7]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id6 [1]
        SKIP 0, 0
        JMP id6
        JMP lost1
id6:    SHIFT_OUT               # ID[6]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id5 [1]
        SKIP 0, 0
        JMP id5
        JMP lost1
id5:    SHIFT_OUT               # ID[5]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id4 [1]
        SKIP 0, 0
        JMP id4
        JMP lost1
id4:    SHIFT_OUT               # ID[4], the first byte's last bit
        SHIFT_IN 0 [1]          #        the bit as sent, and
        PULL                    #        {ID[3:0], 0000} in the fourth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 1
        SKIP 1, 1
        JMP id3 [1]
        SKIP 0, 0
        JMP id3
        JMP lost
id3:    SHIFT_OUT               # ID[3]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id2 [1]
        SKIP 0, 0
        JMP id2
        JMP lost
id2:    SHIFT_OUT               # ID[2]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id1 [1]
        SKIP 0, 0
        JMP id1
        JMP lost
id1:    SHIFT_OUT               # ID[1]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP id0 [1]
        SKIP 0, 0
        JMP id0
        JMP lost
id0:    SHIFT_OUT               # ID[0]
        SHIFT_IN 0 [2]
        SHIFT_IN 1
        SKIP 1, 1
        JMP lost [1]            #         through the identifier or lost on its last bit: the same exit, on the same cycle
        SKIP 0, 0
        JMP lost
        JMP lost
lost1:  PULL                    # lost before ID[4]'s PULL: {ID[3:0], 0000} is still queued and the next frame would send it first; take it and drop it
lost:   PUSH 0, 1               # TXD recessive, as it already is on a loss; the last four (sent, seen) pairs to the host
