# can_rx_destuff.asm with the run test, SKIP_NORUN, adopted 2026-09-28: the
# destuffed stream on pins 2 and 3 and the ACK slot found, at 8 clocks a bit.
# The tree of five single-bit SKIPs, 23 words a cell with its padding, is two
# words, "not five recessive? step over" and "not five dominant? step over",
# and the JMP into the dominant tree, the sixth cycle, is gone: the decision
# is two cycles. The pin copy is the cell's other half: the data bit's level
# is not known to a run test, so pin 2 takes it from a SKIP on the newest bit
# with a side effect for the default and a SET for the other, padded to three
# cycles either way. 12 words a cell for 23, 34 for 56, the same samples on
# the same clocks, the same stream on the pins, the same ACK.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening; pins 2 and 3 push-pull, the stream out
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0, the four before it above
        SHIFT_IN 0              # the idle bus, recessive: the register below the SOF holds a 1
        WAIT 0, 0 [4]           # the SOF's edge: issues on the first clock the bus is dominant, holds through its fifth
bit:    SHIFT_IN 0, 3, 1        # b1: the seventh clock of a data bit, the level through the sixth; pin 3 <- 1: a data slot
        SKIP 0, 0, 2, 0         # b2: pin 2 <- 0; dominant? step over the SET
        SET 2, 1                # b3: recessive: pin 2 <- 1
        SKIP 0, 1               # b3 dominant, b4 recessive: recessive? step over the NOP
        NOP                     # b4: the dominant side's pad
        SKIP_NORUN 5, 1         # b5: not five recessive? step over the JMP
        JMP bits [2]            # b6 to b8: five recessive: the stuff bit at b9
        SKIP_NORUN 5, 0         # b6: not five dominant? step over the JMP
        JMP bits [1]            # b7 to b8: five dominant
        JMP end                 # b7: no run: the REPEAT on b8
bits:   SHIFT_IN 0, 3, 0 [6]    # b9 to b15: the stuff bit, sampled on its seventh clock into the raw history; pin 3 <- 0: not data
end:    REPEAT 32, bit          # b8, or b16 after a stuff bit: the SOF to bit 31
bit2:   SHIFT_IN 0, 3, 1
        SKIP 0, 0, 2, 0
        SET 2, 1
        SKIP 0, 1
        NOP
        SKIP_NORUN 5, 1
        JMP bit2s [2]
        SKIP_NORUN 5, 0
        JMP bit2s [1]
        JMP end2
bit2s:  SHIFT_IN 0, 3, 0 [6]
end2:   REPEAT 10, bit2         # bits 32 to 41, the CRC's last
        SHIFT_IN 0, 3, 0 [1]    # the CRC delimiter, sampled as every bit, the last raw sample; pin 3 <- 0: not data
        SET 0, 0 [7]            # the ACK slot: pulled dominant for the bit
        SET 0, 1 [7]            # the ACK delimiter: let go
gap:    NOP [6]                 # EOF and the intermission: ten recessive bits
        REPEAT 10, gap
        PUSH                    # the last eight raw samples to the host, the delimiter last; halted
