# can_tx_stuff.asm with BRANCH: the SOF and the 11-bit identifier with dynamic
# bit stuffing, the pad on the bus, 12 cycles a bit, driven on the first and
# sampled on the 7th (the level through the 6th, 50%). The decision is a tree
# of BRANCHes: the newest sample picks a side, four BRANCHes ask whether the
# four before it match, out at the first that does not to a ladder of NOPs
# that lands every exit on the next bit edge, the stuff bit at the end of the
# fall-through: five cycles on every path after the sample. Every checked bit
# written out, ID[7] to ID[0]: a run of five cannot end before ID[7]. The host
# writes {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm and reads the
# last eight samples, stuff bits among them. 168 words, 29
# distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [5]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 6
        SHIFT_IN 0 [4]          # sampled on the 7th, held 5, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [5]           # ID7: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id7z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id7l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id7l3
        BRANCH 3, 1, id7l4
        BRANCH 4, 1, id6        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id6                 # the twelfth: the next bit
id7z:   BRANCH 1, 0, id7l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id7l3
        BRANCH 3, 0, id7l4
        BRANCH 4, 0, id6
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id6
id7l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id7l3:  NOP
id7l4:  NOP
id6:    SHIFT_OUT [5]           # ID6: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id6z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id6l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id6l3
        BRANCH 3, 1, id6l4
        BRANCH 4, 1, id5        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id5                 # the twelfth: the next bit
id6z:   BRANCH 1, 0, id6l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id6l3
        BRANCH 3, 0, id6l4
        BRANCH 4, 0, id5
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id5
id6l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id6l3:  NOP
id6l4:  NOP
id5:    SHIFT_OUT [5]           # ID5: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id5z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id5l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id5l3
        BRANCH 3, 1, id5l4
        BRANCH 4, 1, id4        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id4                 # the twelfth: the next bit
id5z:   BRANCH 1, 0, id5l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id5l3
        BRANCH 3, 0, id5l4
        BRANCH 4, 0, id4
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id4
id5l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id5l3:  NOP
id5l4:  NOP
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
id3:    SHIFT_OUT [5]           # ID3: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id3z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id3l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id3l3
        BRANCH 3, 1, id3l4
        BRANCH 4, 1, id2        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id2                 # the twelfth: the next bit
id3z:   BRANCH 1, 0, id3l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id3l3
        BRANCH 3, 0, id3l4
        BRANCH 4, 0, id2
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id2
id3l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id3l3:  NOP
id3l4:  NOP
id2:    SHIFT_OUT [5]           # ID2: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id2z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id2l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id2l3
        BRANCH 3, 1, id2l4
        BRANCH 4, 1, id1        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id1                 # the twelfth: the next bit
id2z:   BRANCH 1, 0, id2l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id2l3
        BRANCH 3, 0, id2l4
        BRANCH 4, 0, id1
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id1
id2l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id2l3:  NOP
id2l4:  NOP
id1:    SHIFT_OUT [5]           # ID1: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id1z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id1l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id1l3
        BRANCH 3, 1, id1l4
        BRANCH 4, 1, id0        # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP id0                 # the twelfth: the next bit
id1z:   BRANCH 1, 0, id1l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id1l3
        BRANCH 3, 0, id1l4
        BRANCH 4, 0, id0
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP id0
id1l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id1l3:  NOP
id1l4:  NOP
id0:    SHIFT_OUT [5]           # ID0: driven, held six
        SHIFT_IN 0              # sampled on the seventh
        BRANCH 0, 1, id0z       # recessive: the recessive tree, cycle 8
        BRANCH 1, 1, id0l2      # dominant: the bit before recessive? no run, three rungs of the ladder
        BRANCH 2, 1, id0l3
        BRANCH 3, 1, id0l4
        BRANCH 4, 1, done       # the bit before that recessive? no run, the last rung is the next bit
        SET 0, 1 [5]            # five dominant: a recessive stuff bit, let go, held six, on the thirteenth
        SHIFT_IN 0 [4]          # sampled on its seventh like every bit, held five, and
        JMP done                # the twelfth: the next bit
id0z:   BRANCH 1, 0, id0l2      # the recessive tree, cycle 9: the bit before dominant? no run
        BRANCH 2, 0, id0l3
        BRANCH 3, 0, id0l4
        BRANCH 4, 0, done
        SET 0, 0 [5]            # five recessive: a dominant stuff bit, driven, held six
        SHIFT_IN 0 [4]
        JMP done
id0l2:  NOP                     # the ladder: an exit from rung r lands r words up it and reaches the next bit on the thirteenth
id0l3:  NOP
id0l4:  NOP
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
