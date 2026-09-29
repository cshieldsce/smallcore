# CAN transmitter, stage 4: the SOF and the 11-bit identifier with dynamic bit
# stuffing, the pad on the bus as in can_tx.asm. The rule: after five bits of
# one level the transmitter inserts one of the other, and the receiver drops
# it. The core has no run counter, but the bus it samples every bit is the
# stream the rule counts, and the last five samples sit in in_shift_reg bits
# 4:0, so the decision is a tree of single-bit SKIPs: the newest bit picks a
# side, then four SKIPs ask whether the four before it match, a JMP out on the
# first that does not, the stuff bit at the end of the fall-through. Seven
# cycles on the longest path after the sample, so a bit is 16 cycles here,
# not 8: the bit is driven on its first cycle and sampled on its ninth, the
# level it held through its eighth (50%), and the tree runs in the seven
# after; at 8 cycles a bit the tree is one cycle too long even sampling on
# the first. The stuff bit is a SET of the other level, a full bit, sampled
# like every bit so the next window counts it; it takes nothing from
# shift_reg. A JMP out of a body is what REPEAT forbids, so every checked bit
# is written out, 27 words each, ID[7] to ID[0]: the four bits before them
# cannot end a run of five. The host writes {SOF 0, ID[10:4]} and {ID[3:0],
# 0000} as for can_tx.asm and reads the last eight samples back, stuff bits
# among them. 224 words.
        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [7]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held eight
        SHIFT_IN 0 [6]          # sampled on the ninth, the level through the eighth, held seven, and
        REPEAT 4, first         # the sixteenth: no run of five can end here
id7:    SHIFT_OUT [7]           # ID7: driven, held eight, cycles 1 to 8 of the bit
        SHIFT_IN 0              # sampled on the ninth: the newest bit of in_shift_reg, the four before it below it
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 10
        JMP id7z                # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit 1 before recessive too? step over the JMP
        JMP id6 [4]             # no run: the next bit on the sixteenth cycle
        SKIP 2, 1
        JMP id6 [3]
        SKIP 3, 1
        JMP id6 [2]
        SKIP 4, 1
        JMP id6 [1]
        NOP [1]                 # five recessive: a dominant stuff bit follows, on the sixteenth cycle
        SET 0, 0 [7]            # the stuff bit, dominant, driven, held eight
        SHIFT_IN 0 [6]          # sampled on its ninth like every bit, held seven
        JMP id6                 # and the sixteenth: the next bit
id7z:   SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP id6 [3]
        SKIP 2, 0
        JMP id6 [2]
        SKIP 3, 0
        JMP id6 [1]
        SKIP 4, 0
        JMP id6
        NOP                     # five dominant: a recessive stuff bit follows
        SET 0, 1 [7]            # the stuff bit, recessive, let go, held eight
        SHIFT_IN 0 [7]          # sampled on its ninth, held eight: the next bit follows
id6:    SHIFT_OUT [7]           # ID6: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id6z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id5 [4]
        SKIP 2, 1
        JMP id5 [3]
        SKIP 3, 1
        JMP id5 [2]
        SKIP 4, 1
        JMP id5 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id5
id6z:   SKIP 1, 0
        JMP id5 [3]
        SKIP 2, 0
        JMP id5 [2]
        SKIP 3, 0
        JMP id5 [1]
        SKIP 4, 0
        JMP id5
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id5:    SHIFT_OUT [7]           # ID5: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id5z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id4 [4]
        SKIP 2, 1
        JMP id4 [3]
        SKIP 3, 1
        JMP id4 [2]
        SKIP 4, 1
        JMP id4 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id4
id5z:   SKIP 1, 0
        JMP id4 [3]
        SKIP 2, 0
        JMP id4 [2]
        SKIP 3, 0
        JMP id4 [1]
        SKIP 4, 0
        JMP id4
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id4:    SHIFT_OUT [6]           # ID4: driven, held seven, and
        PULL                    # {ID[3:0], 0000} in the eighth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id4z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id3 [4]
        SKIP 2, 1
        JMP id3 [3]
        SKIP 3, 1
        JMP id3 [2]
        SKIP 4, 1
        JMP id3 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id3
id4z:   SKIP 1, 0
        JMP id3 [3]
        SKIP 2, 0
        JMP id3 [2]
        SKIP 3, 0
        JMP id3 [1]
        SKIP 4, 0
        JMP id3
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id3:    SHIFT_OUT [7]           # ID3: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id3z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id2 [4]
        SKIP 2, 1
        JMP id2 [3]
        SKIP 3, 1
        JMP id2 [2]
        SKIP 4, 1
        JMP id2 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id2
id3z:   SKIP 1, 0
        JMP id2 [3]
        SKIP 2, 0
        JMP id2 [2]
        SKIP 3, 0
        JMP id2 [1]
        SKIP 4, 0
        JMP id2
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id2:    SHIFT_OUT [7]           # ID2: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id2z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id1 [4]
        SKIP 2, 1
        JMP id1 [3]
        SKIP 3, 1
        JMP id1 [2]
        SKIP 4, 1
        JMP id1 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id1
id2z:   SKIP 1, 0
        JMP id1 [3]
        SKIP 2, 0
        JMP id1 [2]
        SKIP 3, 0
        JMP id1 [1]
        SKIP 4, 0
        JMP id1
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id1:    SHIFT_OUT [7]           # ID1: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id1z                # dominant: the dominant tree
        SKIP 1, 1
        JMP id0 [4]
        SKIP 2, 1
        JMP id0 [3]
        SKIP 3, 1
        JMP id0 [2]
        SKIP 4, 1
        JMP id0 [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP id0
id1z:   SKIP 1, 0
        JMP id0 [3]
        SKIP 2, 0
        JMP id0 [2]
        SKIP 3, 0
        JMP id0 [1]
        SKIP 4, 0
        JMP id0
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
id0:    SHIFT_OUT [7]           # ID0: driven, held eight
        SHIFT_IN 0              # sampled on the ninth
        SKIP 0, 1               # recessive? step over the JMP
        JMP id0z                # dominant: the dominant tree
        SKIP 1, 1
        JMP done [4]
        SKIP 2, 1
        JMP done [3]
        SKIP 3, 1
        JMP done [2]
        SKIP 4, 1
        JMP done [1]
        NOP [1]
        SET 0, 0 [7]
        SHIFT_IN 0 [6]
        JMP done
id0z:   SKIP 1, 0
        JMP done [3]
        SKIP 2, 0
        JMP done [2]
        SKIP 3, 0
        JMP done [1]
        SKIP 4, 0
        JMP done
        NOP
        SET 0, 1 [7]
        SHIFT_IN 0 [7]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
