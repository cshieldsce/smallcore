# can_rx_bits.asm with the run test, SKIP_NORUN, adopted 2026-09-28: the
# destuffed stream through the RX FIFO, a PUSH after every data sample, at 8
# clocks a bit where the tree of SKIPs needed 9. The decision is two words
# and two cycles, so the cell is one SHIFT_IN, the PUSH, two of decision, a
# JMP and the REPEAT with a clock to spare: 9 words a cell for 24, 27 for
# 57. The same bytes to the host, the same ACK, the same bound on the host,
# four bit times to pop.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0, the four before it above
        SHIFT_IN 0              # the idle bus, recessive: the register below the SOF holds a 1
        WAIT 0, 0 [4]           # the SOF's edge, held through its fifth clock
bit:    SHIFT_IN 0              # b1: the seventh clock of a data bit, the level through the sixth
        PUSH                    # b2: the register to the host, the data bit its bit 0
        SKIP_NORUN 5, 1         # b3: not five recessive? step over the JMP
        JMP bits [4]            # b4 to b8: five recessive: the stuff bit at b9
        SKIP_NORUN 5, 0         # b4: not five dominant? step over the JMP
        JMP bits [3]            # b5 to b8: five dominant
        JMP end [2]             # b5 to b7: no run: the REPEAT on b8
bits:   SHIFT_IN 0 [6]          # b9 to b15: the stuff bit into the raw history, no PUSH; the REPEAT on b16
end:    REPEAT 32, bit          # the SOF to bit 31
bit2:   SHIFT_IN 0
        PUSH
        SKIP_NORUN 5, 1
        JMP bit2s [4]
        SKIP_NORUN 5, 0
        JMP bit2s [3]
        JMP end2 [2]
bit2s:  SHIFT_IN 0 [6]
end2:   REPEAT 10, bit2         # bits 32 to 41
        SHIFT_IN 0 [1]          # the CRC delimiter, sampled; the slot's edge two clocks on
        SET 0, 0 [7]            # the ACK slot: pulled dominant for the bit
        SET 0, 1 [7]            # the ACK delimiter: let go
gap:    NOP [6]                 # EOF and the intermission
        REPEAT 10, gap          # halted
