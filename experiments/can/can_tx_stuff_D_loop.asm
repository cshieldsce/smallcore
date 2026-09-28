# can_tx_stuff.asm with SKIP_SAME, the run counter: the SOF and the 11-bit
# identifier with dynamic bit stuffing, the pad on the bus, 10 cycles a bit,
# driven on the first and sampled on the 5th (the level through the 4th, 40%).
# The decision is the counter's test, five the same? a SKIP_SAME over the JMP
# to the next bit, then the level, SKIP 0 over the JMP to the dominant stuff
# bit: four cycles on every path after the sample. ID[7], ID[6], ID[5] one
# REPEAT body, ID[3] to ID[0] another, ID[4] with its PULL written out between
# them in the unrolled cell's shape; the REPEAT's cycle and the JMP over the
# stuff code are paid for by sampling earlier. The host writes {SOF 0,
# ID[10:4]} and {ID[3:0], 0000} as for can_tx.asm and reads the last eight
# samples, stuff bits among them. 46 words, 27 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [3]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 4
        SHIFT_IN 0 [4]          # sampled on the 5th, held 5, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [3]           # ID7: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP end1 [2]            # no run: the REPEAT on the tenth
        SKIP 0, 0               # dominant? step over the JMP
        JMP id7d [2]            # five recessive: a dominant stuff bit on the eleventh
        NOP [2]                 # five dominant: a recessive stuff bit on the eleventh
id7r:   SET 0, 1 [4]
        SHIFT_IN 0 [2]
        JMP end1
id7d:   SET 0, 0 [4]
        SHIFT_IN 0 [3]          # the REPEAT follows
end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]
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
id3:    SHIFT_OUT [3]           # ID3: driven, held four
        SHIFT_IN 0              # sampled on the fifth
        SKIP_SAME 5             # five the same? step over the JMP
        JMP end2 [2]            # no run: the REPEAT on the tenth
        SKIP 0, 0               # dominant? step over the JMP
        JMP id3d [2]            # five recessive: a dominant stuff bit on the eleventh
        NOP [2]                 # five dominant: a recessive stuff bit on the eleventh
id3r:   SET 0, 1 [4]
        SHIFT_IN 0 [2]
        JMP end2
id3d:   SET 0, 0 [4]
        SHIFT_IN 0 [3]          # the REPEAT follows
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
