# can_tx_stuff.asm with today's ISA and REPEAT: the SOF and the 11-bit
# identifier with dynamic bit stuffing, the pad on the bus, 16 cycles a bit,
# driven on the first and sampled on the 8th (the level through the 7th,
# 43.75%). The baseline's tree of single-bit SKIPs, seven cycles on the
# longest path after the sample, every exit a JMP to the REPEAT: a JMP may
# land on the REPEAT that ends its body, so the cell is a body, which the
# 224-word baseline did not use. ID[7], ID[6], ID[5] one REPEAT body, ID[3] to
# ID[0] another, ID[4] with its PULL written out between them in the unrolled
# cell's shape; the REPEAT's cycle and the JMP over the stuff code are paid
# for by sampling earlier. The host writes {SOF 0, ID[10:4]} and {ID[3:0],
# 0000} as for can_tx.asm and reads the last eight samples, stuff bits among
# them. 91 words, 44 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
first:  SHIFT_OUT [6]           # the SOF, ID[10], ID[9], ID[8]: driven on the first cycle, held 7
        SHIFT_IN 0 [7]          # sampled on the 8th, held 8, and
        REPEAT 4, first         # the last cycle: no run of five can end here
id7:    SHIFT_OUT [6]           # ID7: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree
        JMP id7z                # dominant: the dominant tree
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP end1 [4]            # no run: the REPEAT on the sixteenth cycle
        SKIP 2, 1
        JMP end1 [3]
        SKIP 3, 1
        JMP end1 [2]
        SKIP 4, 1
        JMP end1 [1]
        NOP [2]                 # five recessive: a dominant stuff bit follows on the seventeenth
        SET 0, 0 [7]            # the stuff bit, dominant, driven, held eight
        SHIFT_IN 0 [5]          # sampled on its eighth like every bit, held six, and
        JMP end1                # the REPEAT: the next bit
id7z:   SKIP 1, 0               # the dominant tree: the bit before dominant too? step over the JMP
        JMP end1 [3]
        SKIP 2, 0
        JMP end1 [2]
        SKIP 3, 0
        JMP end1 [1]
        SKIP 4, 0
        JMP end1
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [7]            # the stuff bit, recessive, let go, held eight
        SHIFT_IN 0 [6]          # sampled on its eighth, held seven: the REPEAT follows
end1:   REPEAT 3, id7           # ID[7], ID[6], ID[5]
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
id3:    SHIFT_OUT [6]           # ID3: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree
        JMP id3z                # dominant: the dominant tree
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP end2 [4]            # no run: the REPEAT on the sixteenth cycle
        SKIP 2, 1
        JMP end2 [3]
        SKIP 3, 1
        JMP end2 [2]
        SKIP 4, 1
        JMP end2 [1]
        NOP [2]                 # five recessive: a dominant stuff bit follows on the seventeenth
        SET 0, 0 [7]            # the stuff bit, dominant, driven, held eight
        SHIFT_IN 0 [5]          # sampled on its eighth like every bit, held six, and
        JMP end2                # the REPEAT: the next bit
id3z:   SKIP 1, 0               # the dominant tree: the bit before dominant too? step over the JMP
        JMP end2 [3]
        SKIP 2, 0
        JMP end2 [2]
        SKIP 3, 0
        JMP end2 [1]
        SKIP 4, 0
        JMP end2
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [7]            # the stuff bit, recessive, let go, held eight
        SHIFT_IN 0 [6]          # sampled on its eighth, held seven: the REPEAT follows
end2:   REPEAT 4, id3           # ID[3] down to ID[0]
done:   PUSH 0, 1               # let go: recessive, the bus idle; the last eight samples to the host, stuff bits among them
