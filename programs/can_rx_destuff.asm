# CAN receiver, RX3 to RX5: the stuff condition seen, the stuff bit dropped,
# the destuffed stream recovered, at 8 cycles a bit. The bus on gpio 0 as
# can_rx.asm listens, the level through the sixth clock taken on the seventh.
# After every sample stage 4's tree of single-bit SKIPs asks whether the last
# five samples were one level, the raw history in in_shift_reg bits 4:0, and
# when they were, the next bit is a stuff bit: sampled like every bit, since
# the history must hold it, and handed on as nothing. The decision is five
# cycles on the recessive side and six on the dominant, the JMP into the
# dominant tree, and every exit is padded to the REPEAT: a receiver's
# decision has until the next sample, not the next edge, so the cell is one
# SHIFT_IN, six of decision and the REPEAT, eight clocks, and the bit rate
# holds. What the receiver cannot do is gather the destuffed bits into a byte:
# the one register is the raw history, so the stream leaves on pins, pin 2 the
# data bit, set by the tree's first word on each side, and pin 3 whether the
# slot was data, cleared on the stuff bit's sample; a receiver on those two
# pins reads the frame as the transmitter's host wrote it. The body runs once
# per data bit, a stuff bit inside it, so REPEAT counts data bits and the
# ACK slot is found: 42 for DLC 1, a constant, since nothing loads rc from the
# DLC just received. The register must hold a recessive sample below the SOF,
# one SHIFT_IN of the idle bus before the WAIT, or the SOF and three dominant
# identifier bits would read as five with the zero fill. After the CRC
# delimiter the slot is pulled dominant for a bit, let go, and EOF and the
# intermission waited out; the host reads the last eight raw samples, the
# delimiter last. 56 words, 37 distinct.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening; pins 2 and 3 push-pull, the stream out
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0, the four before it above
        SHIFT_IN 0              # the idle bus, recessive: the register below the SOF holds a 1
        WAIT 0, 0 [4]           # the SOF's edge: issues on the first clock the bus is dominant, holds through its fifth
bit:    SHIFT_IN 0, 3, 1        # b1: the seventh clock of a data bit, the level through the sixth; pin 3 <- 1: this slot is data
        SKIP 0, 1               # b2: recessive? step over the JMP: the recessive tree
        JMP bitz                # b3: dominant: the dominant tree
        SKIP 1, 1, 2, 1         # b3: pin 2 <- 1, the data bit, recessive; the bit before recessive too? step over the JMP
        JMP end [3]             # b4 to b7: no run: the REPEAT on b8
        SKIP 2, 1               # b4
        JMP end [2]             # b5 to b7
        SKIP 3, 1               # b5
        JMP end [1]             # b6 to b7
        SKIP 4, 0               # b6: the fifth dominant? no run: step over the JMP
        JMP bits [1]            # b7 to b8: five recessive: the next bit is a stuff bit
        JMP end                 # b7: the REPEAT on b8
bits:   SHIFT_IN 0, 3, 0 [5]    # b9 to b14: the stuff bit, sampled on its seventh clock into the raw history; pin 3 <- 0: not data
        JMP end                 # b15: the REPEAT on b16, a clock before the next data bit's sample
bitz:   SKIP 1, 0, 2, 0         # b4: pin 2 <- 0, the data bit, dominant; the bit before dominant too? step over the JMP
        JMP end [2]             # b5 to b7
        SKIP 2, 0               # b5
        JMP end [1]             # b6 to b7
        SKIP 3, 0               # b6
        JMP end                 # b7
        SKIP 4, 1               # b7: the fifth recessive? no run: step over the JMP, onto the REPEAT
        JMP bits                # b8: five dominant: the stuff bit at b9
end:    REPEAT 32, bit         # b8: the SOF to bit 31
bit2:    SHIFT_IN 0, 3, 1        # b1: the seventh clock of a data bit, the level through the sixth; pin 3 <- 1: this slot is data
        SKIP 0, 1               # b2: recessive? step over the JMP: the recessive tree
        JMP bit2z                # b3: dominant: the dominant tree
        SKIP 1, 1, 2, 1         # b3: pin 2 <- 1, the data bit, recessive; the bit before recessive too? step over the JMP
        JMP end2 [3]             # b4 to b7: no run: the REPEAT on b8
        SKIP 2, 1               # b4
        JMP end2 [2]             # b5 to b7
        SKIP 3, 1               # b5
        JMP end2 [1]             # b6 to b7
        SKIP 4, 0               # b6: the fifth dominant? no run: step over the JMP
        JMP bit2s [1]            # b7 to b8: five recessive: the next bit is a stuff bit
        JMP end2                 # b7: the REPEAT on b8
bit2s:   SHIFT_IN 0, 3, 0 [5]    # b9 to b14: the stuff bit, sampled on its seventh clock into the raw history; pin 3 <- 0: not data
        JMP end2                 # b15: the REPEAT on b16, a clock before the next data bit's sample
bit2z:   SKIP 1, 0, 2, 0         # b4: pin 2 <- 0, the data bit, dominant; the bit before dominant too? step over the JMP
        JMP end2 [2]             # b5 to b7
        SKIP 2, 0               # b5
        JMP end2 [1]             # b6 to b7
        SKIP 3, 0               # b6
        JMP end2                 # b7
        SKIP 4, 1               # b7: the fifth recessive? no run: step over the JMP, onto the REPEAT
        JMP bit2s                # b8: five dominant: the stuff bit at b9
end2:   REPEAT 10, bit2        # bits 32 to 41, the CRC's last
        SHIFT_IN 0, 3, 0 [1]    # the CRC delimiter, sampled as every bit, the last raw sample; pin 3 <- 0: not data
        SET 0, 0 [7]            # the ACK slot: pulled dominant for the bit
        SET 0, 1 [7]            # the ACK delimiter: let go
gap:    NOP [6]                 # EOF and the intermission: ten recessive bits
        REPEAT 10, gap
        PUSH                    # the last eight raw samples to the host, the delimiter last; halted
