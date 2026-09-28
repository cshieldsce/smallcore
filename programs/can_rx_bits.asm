# CAN receiver, RX5 through the FIFO: can_rx_destuff.asm with the destuffed
# stream handed to the host instead of put on pins. The one register is the
# raw history the run test reads, so a byte of destuffed data cannot be
# gathered in it; what can be done is a PUSH after every data sample and none
# after a stuff bit: bit 0 of every byte the host reads is the next data bit,
# and 42 pops are the frame, the host's to assemble. The PUSH is the ninth
# cycle of the cell, one SHIFT_IN, the PUSH, six of decision and the REPEAT,
# and the dominant tree's longest path has no cycle to spare, so a bit is 9
# clocks here, not 8: the FIFO as the second stream costs an eighth of the bit
# rate. The RX FIFO takes a byte a bit and holds four: the host must pop
# within four bit times of every byte, or the fifth PUSH stalls the receiver
# inside the frame. The ACK slot is found and pulled as before. 57
# words, 36 distinct.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0, the four before it above
        SHIFT_IN 0              # the idle bus, recessive: the register below the SOF holds a 1
        WAIT 0, 0 [4]           # the SOF's edge, held through its fifth clock
bit:    SHIFT_IN 0              # b1: the seventh clock of a data bit, the level through the sixth
        PUSH                    # b2: the register to the host, the data bit its bit 0
        SKIP 0, 1               # b3: recessive? the recessive tree
        JMP bitz                # b4: dominant: the dominant tree
        SKIP 1, 1               # b4
        JMP end [3]             # b5 to b8: no run: the REPEAT on b9
        SKIP 2, 1               # b5
        JMP end [2]             # b6 to b8
        SKIP 3, 1               # b6
        JMP end [1]             # b7 to b8
        SKIP 4, 0               # b7: no run: step over the JMP
        JMP bits [1]            # b8 to b9: five recessive: a stuff bit next
        JMP end                 # b8: the REPEAT on b9
bits:   SHIFT_IN 0 [5]          # b10 to b15: the stuff bit into the raw history, no PUSH
        JMP end [1]             # b16 to b17: the REPEAT on b18
bitz:   SKIP 1, 0               # b5
        JMP end [2]             # b6 to b8
        SKIP 2, 0               # b6
        JMP end [1]             # b7 to b8
        SKIP 3, 0               # b7
        JMP end                 # b8
        SKIP 4, 1               # b8: no run: step over the JMP, onto the REPEAT
        JMP bits                # b9: five dominant: the stuff bit at b10
end:    REPEAT 32, bit         # b9: the SOF to bit 31
bit2:    SHIFT_IN 0              # b1: the seventh clock of a data bit, the level through the sixth
        PUSH                    # b2: the register to the host, the data bit its bit 0
        SKIP 0, 1               # b3: recessive? the recessive tree
        JMP bit2z                # b4: dominant: the dominant tree
        SKIP 1, 1               # b4
        JMP end2 [3]             # b5 to b8: no run: the REPEAT on b9
        SKIP 2, 1               # b5
        JMP end2 [2]             # b6 to b8
        SKIP 3, 1               # b6
        JMP end2 [1]             # b7 to b8
        SKIP 4, 0               # b7: no run: step over the JMP
        JMP bit2s [1]            # b8 to b9: five recessive: a stuff bit next
        JMP end2                 # b8: the REPEAT on b9
bit2s:   SHIFT_IN 0 [5]          # b10 to b15: the stuff bit into the raw history, no PUSH
        JMP end2 [1]             # b16 to b17: the REPEAT on b18
bit2z:   SKIP 1, 0               # b5
        JMP end2 [2]             # b6 to b8
        SKIP 2, 0               # b6
        JMP end2 [1]             # b7 to b8
        SKIP 3, 0               # b7
        JMP end2                 # b8
        SKIP 4, 1               # b8: no run: step over the JMP, onto the REPEAT
        JMP bit2s                # b9: five dominant: the stuff bit at b10
end2:   REPEAT 10, bit2        # bits 32 to 41
        SHIFT_IN 0 [2]          # the CRC delimiter, sampled, the last raw sample; the slot's edge three clocks on
        SET 0, 0 [8]            # the ACK slot: pulled dominant for the bit, nine clocks
        SET 0, 1 [8]            # the ACK delimiter: let go
gap:    NOP [7]                 # EOF and the intermission: ten recessive bits, nine clocks each
        REPEAT 10, gap          # halted
