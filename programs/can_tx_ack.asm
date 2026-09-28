# CAN transmitter, stage 3: the SOF and the 11-bit identifier, then the ACK
# slot. can_tx.asm's frame, the pad on the bus, 8 cycles a bit; then the
# transmitter lets go for one bit, the ACK slot, and samples it as it samples
# every bit: a receiver that took the frame pulls it dominant. The ACK
# delimiter is recessive and the decision falls inside it. Nothing to
# remember: the bit sent in the slot is the program's own constant, so the
# slot's sample, the newest bit of in_shift_reg, decides on its own, SKIP 0, 1.
# Acked: {ID[6:0], ACK 0} to the host and the halt, the bus idle, EOF and the
# intermission the halt's. Not acked: the same byte with ACK 1, then EOF and
# the intermission, ten recessive bits, then the frame again from the host's
# next two bytes: the stand-in for CAN's retransmission until error signalling
# exists, the host supplying the bytes again, since nothing but PULL loads
# shift_reg. The PULL's stall between frames is the bus idle: safe, unlike a
# stall inside one. 21 words.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
frame:  PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty: between frames)
cell:   SHIFT_OUT [5]           # a bit: drive it, a 0 pulls the bus dominant, a 1 lets go, six cycles
        SHIFT_IN 0              #        sample the bus on the seventh, and
        REPEAT 7, cell          #        the eighth: seven bits, the SOF to ID[5]
        SHIFT_OUT [5]           # ID[4], the first byte's last bit, the same cell unrolled
        SHIFT_IN 0              #
        PULL                    #        {ID[3:0], 0000} in the eighth cycle (stalls while the FIFO is empty: the bit stretches)
cell2:  SHIFT_OUT [5]           # ID[3] down to ID[0], the cell again
        SHIFT_IN 0
        REPEAT 4, cell2
        SET 0, 1 [5]            # ACK slot: let go, recessive; a receiver that took the frame pulls it dominant
        SHIFT_IN 0 [1]          #           sample it on the seventh cycle, as every bit, and hold the eighth
        SKIP 0, 1               # ACK delimiter, recessive as the pin stands: not acked? the sample recessive: step over the JMP
        JMP acked [5]           #           acked: the delimiter's next six cycles
        PUSH [6]                # not acked: {ID[6:0], ACK 1} to the host, the delimiter's other seven cycles
gap:    NOP [6]                 # EOF and the intermission: ten recessive bits, and
        REPEAT 10, gap          #
        JMP frame               # the frame again, from the host's next two bytes
acked:  PUSH                    # acked: {ID[6:0], ACK 0} to the host; halted, the bus idle: EOF and the intermission are the halt's
