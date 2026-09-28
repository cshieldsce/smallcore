# can_tx_stuff.asm with BRANCH: the SOF and the 11-bit identifier with dynamic
# bit stuffing, the pad on the bus, 12 cycles a bit, driven on the first and
# sampled on the 6th (the level through the 5th, 41.6667%). The decision is a
# tree of BRANCHes: the newest sample picks a side, four BRANCHes ask whether
# the four before it match, out at the first that does not to a ladder of NOPs
# that lands every exit on the next bit edge, the stuff bit at the end of the
# fall-through: five cycles on every path after the sample. ID[7], ID[6],
# ID[5] one REPEAT body, ID[3] to ID[0] another, ID[4] with its PULL written
# out between them in the unrolled cell's shape; the REPEAT's cycle is paid
# for by sampling earlier. The host writes {SOF 0, ID[10:4]} and {ID[3:0],
# 0000} as for can_tx.asm and reads the last eight samples, stuff bits among
# them. 74 words, 36 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [4]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 5
        SHIFT_IN 0 [5]          # sampled on the 6th, held 6, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [4]           # ID7: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH 0, 1, id7z       # recessive: the recessive tree, cycle 7
        BRANCH 1, 1, id7l2      # dominant: the bit before recessive? no run, the ladder
        BRANCH 2, 1, id7l3
        BRANCH 3, 1, id7l4
        BRANCH 4, 1, end1       # the last rung is the REPEAT
        NOP                     # five dominant: a recessive stuff bit on the thirteenth
        SET 0, 1 [5]
        SHIFT_IN 0 [3]
        JMP end1
id7z:   BRANCH 1, 0, id7l2      # the recessive tree: the bit before dominant? no run
        BRANCH 2, 0, id7l3
        BRANCH 3, 0, id7l4
        BRANCH 4, 0, end1
        NOP
        SET 0, 0 [5]
        SHIFT_IN 0 [3]
        JMP end1
id7l2:  NOP
id7l3:  NOP
id7l4:  NOP
end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]
id4:    SHIFT_OUT [4]           # ID4: driven, held five, and
        PULL                    # {ID[3:0], 0000} in the sixth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id4z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id4l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id4l3
        BRANCH 3, 1, id4l4
        BRANCH 4, 1, id3        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id3                 # the twelfth: the next bit
id4z:   BRANCH 1, 0, id4l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id4l3
        BRANCH 3, 0, id4l4
        BRANCH 4, 0, id3
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id3
id4l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id4l3:  NOP
id4l4:  NOP
id3:    SHIFT_OUT [4]           # ID3: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        BRANCH 0, 1, id3z       # recessive: the recessive tree, cycle 7
        BRANCH 1, 1, id3l2      # dominant: the bit before recessive? no run, the ladder
        BRANCH 2, 1, id3l3
        BRANCH 3, 1, id3l4
        BRANCH 4, 1, end2       # the last rung is the REPEAT
        NOP                     # five dominant: a recessive stuff bit on the thirteenth
        SET 0, 1 [5]
        SHIFT_IN 0 [3]
        JMP end2
id3z:   BRANCH 1, 0, id3l2      # the recessive tree: the bit before dominant? no run
        BRANCH 2, 0, id3l3
        BRANCH 3, 0, id3l4
        BRANCH 4, 0, end2
        NOP
        SET 0, 0 [5]
        SHIFT_IN 0 [3]
        JMP end2
id3l2:  NOP
id3l3:  NOP
id3l4:  NOP
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
