# can_rx_bits.asm with BRANCH (candidate A): the destuffed stream through
# the RX FIFO, a PUSH after every data sample, at 8 clocks a bit. The
# baseline's cell is nine: one SHIFT_IN, the PUSH, six of decision on the
# dominant side, the JMP into the dominant tree being the sixth, and the
# REPEAT. A branch that is one cycle taken or not takes the JMP out: five
# BRANCHes on either side, the dominant tree entered by the first, every
# no-run exit a branch into a ladder of NOPs that lands on the REPEAT, and
# the stuff path a JMP from the fall-through of the last. The sample stays on
# the sixth clock, read on the seventh; the stuff bit is sampled on its
# seventh and not pushed; the ACK slot is found and pulled as before.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0, the four before it above
        SHIFT_IN 0              # the idle bus, recessive: the register below the SOF holds a 1
        WAIT 0, 0 [4]           # the SOF's edge, held through its fifth clock
bit:    SHIFT_IN 0              # b1: the seventh clock of a data bit, the level through the sixth
        PUSH                    # b2: the register to the host, the data bit its bit 0
        BRANCH 0, 0, bitz       # b3: dominant? the dominant tree
        BRANCH 1, 0, p3         # b4: the bit before dominant: no run, three NOPs to the REPEAT
        BRANCH 2, 0, p2         # b5
        BRANCH 3, 0, p1         # b6
        BRANCH 4, 0, end        # b7: no run: the REPEAT on b8
        JMP bits                # b8: five recessive: the stuff bit at b9
bitz:   BRANCH 1, 1, p3         # b4
        BRANCH 2, 1, p2         # b5
        BRANCH 3, 1, p1         # b6
        BRANCH 4, 1, end        # b7
        JMP bits                # b8: five dominant
bits:   SHIFT_IN 0 [5]          # b9 to b14: the stuff bit into the raw history, no PUSH
        JMP end                 # b15: the REPEAT on b16
p3:     NOP                     # b5
p2:     NOP                     # b6
p1:     NOP                     # b7
end:    REPEAT 32, bit          # b8: the SOF to bit 31
bit2:   SHIFT_IN 0
        PUSH
        BRANCH 0, 0, bit2z
        BRANCH 1, 0, q3
        BRANCH 2, 0, q2
        BRANCH 3, 0, q1
        BRANCH 4, 0, end2
        JMP bit2s
bit2z:  BRANCH 1, 1, q3
        BRANCH 2, 1, q2
        BRANCH 3, 1, q1
        BRANCH 4, 1, end2
        JMP bit2s
bit2s:  SHIFT_IN 0 [5]
        JMP end2
q3:     NOP
q2:     NOP
q1:     NOP
end2:   REPEAT 10, bit2         # bits 32 to 41
        SHIFT_IN 0 [1]          # the CRC delimiter, sampled; the slot's edge two clocks on
        SET 0, 0 [7]            # the ACK slot: pulled dominant for the bit
        SET 0, 1 [7]            # the ACK delimiter: let go
gap:    NOP [6]                 # EOF and the intermission
        REPEAT 10, gap          # halted
