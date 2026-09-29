# CAN transmitter, stage 5A: a complete base-format data frame, unopposed, the
# pad on the bus as in can_tx.asm, stuffed as in can_tx_stuff.asm: the SOF,
# the 11-bit identifier, RTR, IDE, r0 (dominant: a data frame, base format),
# the DLC, one data byte, the 15-bit CRC the host computed; then the fixed
# form, the CRC delimiter, the ACK slot let go and sampled, the ACK delimiter,
# EOF and the intermission, every bit 16 cycles. The stuffing decision is
# stage 4's tree of single-bit SKIPs, seven cycles after the sample, so a bit
# is 16 cycles, driven on its first and sampled on its eighth, the level it
# held through its seventh (43.75%), the loop form's sample point.
#
# The program's size shapes the host's bytes. The stuffed region is 34 + 8 DLC
# bits, 42 here, a PULL every eight, and a 27-word cell for every checked bit;
# stage 4's shape, a one-cell body broken at every PULL, is 317 words for a
# 256-word program memory, 262 with no data at all. So the body is eight cells
# with the PULL in the first, run 4 + DLC times, and the host's bytes are cut
# where its PULLs fall: {SOF, ID[10], ID[9], 00000}, then eight stream bits a
# byte, ID[8:1], {ID[0], RTR, IDE, r0, DLC[3:0]}, the data byte, CRC[14:7],
# {CRC[6:0], 0}: 5 + DLC bytes, six here, through a 4-deep FIFO. The body
# checks every bit it sends, ID[9] first, so the register must hold a
# recessive sample below the SOF: one SHIFT_IN of the idle bus before the
# PULL, or ID[10] = ID[9] = 0 would read as five dominant with the zeros the
# register fills with. The same words send any length: the body's REPEAT
# count is the one word that changes, so a payload length is a program.
#
# After the CRC the form is fixed and nothing is stuffed: the delimiter is a
# SET, the slot is sampled as every bit was, the ACK delimiter carries the
# PUSH, {the stream's last seven samples, ACK} to the host, and EOF and the
# intermission are ten NOPs in a REPEAT. Acked, the program halts on the idle
# bus; not acked, it goes round for the host's six bytes again, stage 3's
# stand-in for retransmission. 233 words, 86 distinct.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0], the fields in order, the CRC
frame:  SHIFT_IN 0              # the idle bus, recessive, sampled once: the register below the SOF holds a 1
        PULL                    # {SOF, ID[10], ID[9], 00000} (stalls while the FIFO is empty: between frames, the bus idle)
lead:   SHIFT_OUT [6]           # the SOF and ID[10]: driven on the first cycle, held seven
        SHIFT_IN 0 [7]          # sampled on the eighth, the level through the seventh, held eight, and
        REPEAT 2, lead          # the sixteenth: no run of five can end here
b0:     SHIFT_OUT [5]           # the body's first bit: driven on the first cycle, held six, and
        PULL                    # the next byte in the seventh (stalls while the FIFO is empty: the bit stretches, every bit after it late)
        SHIFT_IN 0              # sampled on the eighth, the newest bit of in_shift_reg, the four before it below it
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b0z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b1 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b1 [4]
        SKIP 3, 1
        JMP b1 [3]
        SKIP 4, 1
        JMP b1 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b1                  # the next bit
b0z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b1 [4]
        SKIP 2, 0
        JMP b1 [3]
        SKIP 3, 0
        JMP b1 [2]
        SKIP 4, 0
        JMP b1 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b1:     SHIFT_OUT [6]           # bit 1 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b1z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b2 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b2 [4]
        SKIP 3, 1
        JMP b2 [3]
        SKIP 4, 1
        JMP b2 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b2                  # the next bit
b1z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b2 [4]
        SKIP 2, 0
        JMP b2 [3]
        SKIP 3, 0
        JMP b2 [2]
        SKIP 4, 0
        JMP b2 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b2:     SHIFT_OUT [6]           # bit 2 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b2z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b3 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b3 [4]
        SKIP 3, 1
        JMP b3 [3]
        SKIP 4, 1
        JMP b3 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b3                  # the next bit
b2z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b3 [4]
        SKIP 2, 0
        JMP b3 [3]
        SKIP 3, 0
        JMP b3 [2]
        SKIP 4, 0
        JMP b3 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b3:     SHIFT_OUT [6]           # bit 3 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b3z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b4 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b4 [4]
        SKIP 3, 1
        JMP b4 [3]
        SKIP 4, 1
        JMP b4 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b4                  # the next bit
b3z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b4 [4]
        SKIP 2, 0
        JMP b4 [3]
        SKIP 3, 0
        JMP b4 [2]
        SKIP 4, 0
        JMP b4 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b4:     SHIFT_OUT [6]           # bit 4 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b4z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b5 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b5 [4]
        SKIP 3, 1
        JMP b5 [3]
        SKIP 4, 1
        JMP b5 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b5                  # the next bit
b4z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b5 [4]
        SKIP 2, 0
        JMP b5 [3]
        SKIP 3, 0
        JMP b5 [2]
        SKIP 4, 0
        JMP b5 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b5:     SHIFT_OUT [6]           # bit 5 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b5z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b6 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b6 [4]
        SKIP 3, 1
        JMP b6 [3]
        SKIP 4, 1
        JMP b6 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b6                  # the next bit
b5z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b6 [4]
        SKIP 2, 0
        JMP b6 [3]
        SKIP 3, 0
        JMP b6 [2]
        SKIP 4, 0
        JMP b6 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b6:     SHIFT_OUT [6]           # bit 6 of the body: driven, held seven
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b6z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP b7 [5]              # no run: the next bit on the seventeenth cycle
        SKIP 2, 1
        JMP b7 [4]
        SKIP 3, 1
        JMP b7 [3]
        SKIP 4, 1
        JMP b7 [2]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth like every bit, held eight, and
        JMP b7                  # the next bit
b6z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP b7 [4]
        SKIP 2, 0
        JMP b7 [3]
        SKIP 3, 0
        JMP b7 [2]
        SKIP 4, 0
        JMP b7 [1]
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [8]          # sampled on its eighth, held nine: the next bit follows
b7:     SHIFT_OUT [6]           # bit 7 of the body: driven, held seven, the body's last
        SHIFT_IN 0              # sampled on the eighth
        SKIP 0, 1               # recessive? step over the JMP: the recessive tree, cycle 9
        JMP b7z                 # dominant: the dominant tree, cycle 11 there
        SKIP 1, 1               # the bit before recessive too? step over the JMP
        JMP end [4]             # no run: the REPEAT on the sixteenth cycle
        SKIP 2, 1
        JMP end [3]
        SKIP 3, 1
        JMP end [2]
        SKIP 4, 1
        JMP end [1]
        NOP [2]                 # five recessive: a dominant stuff bit follows, on the seventeenth cycle
        SET 0, 0 [6]            # the stuff bit, dominant, driven, held seven
        SHIFT_IN 0 [6]          # sampled on its eighth like every bit, held seven, and
        JMP end                 # the REPEAT
b7z:    SKIP 1, 0               # the dominant tree, cycle 11: the bit before dominant too? step over the JMP
        JMP end [3]
        SKIP 2, 0
        JMP end [2]
        SKIP 3, 0
        JMP end [1]
        SKIP 4, 0
        JMP end
        NOP [1]                 # five dominant: a recessive stuff bit follows
        SET 0, 1 [6]            # the stuff bit, recessive, let go, held seven
        SHIFT_IN 0 [7]          # sampled on its eighth, held eight: the REPEAT follows
end:    REPEAT 5, b0            # 4 + DLC runs of the body: ID[8] to the CRC's last bit, or its stuff bit
        SET 0, 1 [15]           # the CRC delimiter: recessive, let go, a full bit
        NOP [6]                 # the ACK slot: let go still, and
        SHIFT_IN 0 [8]          # sampled on its eighth like every bit: a receiver that took the frame pulls it dominant
        PUSH [15]               # the ACK delimiter, recessive: {the stream's last seven samples, ACK} to the host (stalls while the RX FIFO is full: recessive, EOF's level, harmless)
gap:    NOP [14]                # EOF and the intermission: ten recessive bits, and
        REPEAT 10, gap
        SKIP 0, 0               # acked? step over the JMP: halted, the bus idle
        JMP frame               # not acked: the frame again, from the host's next six bytes
