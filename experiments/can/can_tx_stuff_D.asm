# can_tx_stuff.asm with SKIP_SAME, the run counter: the SOF and the 11-bit
# identifier with dynamic bit stuffing, the pad on the bus, 10 cycles a bit,
# driven on the first and sampled on the 6th (the level through the 5th, 50%).
# The decision is the counter's test, five the same? a SKIP_SAME over the JMP
# to the next bit, then the level, SKIP 0 over the JMP to the dominant stuff
# bit: four cycles on every path after the sample. Every checked bit written
# out, ID[7] to ID[0]: a run of five cannot end before ID[7]. The host writes
# {SOF 0, ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm and reads the last
# eight samples, stuff bits among them. 104 words, 39 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [4]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 5
        SHIFT_IN 0 [3]          # sampled on the 6th, held 4, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [4]           # ID7: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id6 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id7d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id7r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id6                 # the tenth: the next bit
id7d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id6:    SHIFT_OUT [4]           # ID6: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id5 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id6d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id6r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id5                 # the tenth: the next bit
id6d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id5:    SHIFT_OUT [4]           # ID5: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id4 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id5d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id5r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id4                 # the tenth: the next bit
id5d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id4:    SHIFT_OUT [3]           # ID4: driven, held four, and
        PULL                    # {ID[3:0], 0000} in the fifth cycle (stalls while the FIFO is empty: the bit stretches)
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id3 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id4d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id4r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id3                 # the tenth: the next bit
id4d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id3:    SHIFT_OUT [4]           # ID3: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id2 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id3d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id3r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id2                 # the tenth: the next bit
id3d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id2:    SHIFT_OUT [4]           # ID2: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id1 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id2d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id2r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id1                 # the tenth: the next bit
id2d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id1:    SHIFT_OUT [4]           # ID1: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP id0 [2]             # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id1d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id1r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP id0                 # the tenth: the next bit
id1d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
id0:    SHIFT_OUT [4]           # ID0: driven, held five
        SHIFT_IN 0              # sampled on the sixth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP done [2]            # no run: the next bit on the eleventh
        SKIP 0, 0               # dominant? step over the JMP
        JMP id0d [1]            # five recessive: a dominant stuff bit on the eleventh
        NOP [1]                 # five dominant: a recessive stuff bit on the eleventh
id0r:   SET 0, 1 [4]            # the stuff bit, recessive, let go, held five
        SHIFT_IN 0 [3]          # sampled on its sixth like every bit, held four, and
        JMP done                # the tenth: the next bit
id0d:   SET 0, 0 [4]            # the stuff bit, dominant, driven, held five
        SHIFT_IN 0 [4]          # sampled on its sixth, held five: the next bit follows
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
