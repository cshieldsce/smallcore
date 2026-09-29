# CAN transmitter, stage 1: the SOF and the 11-bit standard identifier, nothing
# after them. One bus pin, gpio 0 = CAN_TX, open-drain: a 0 is dominant and
# pulls the bus down, a 1 is recessive and lets go; gpio_in 0 is the bus read
# back. No clock line: a bit is 8 cycles, driven on its first and sampled on
# its seventh, the level the bus held through its sixth (75%, a CAN sample
# point), the words a receiver would use. The host writes the 12 bits MSB
# first as two bytes, {SOF 0, ID[10:4]} and {ID[3:0], 0000}, the low nibble
# unsent: the register zero-fills and a 0 is dominant, so nothing goes out
# that the host did not write. The second byte's PULL takes the eighth cycle
# of ID[4]'s bit, the cycle the REPEAT has in the other cells, so that cell is
# unrolled. After ID[0] the bus is let go, recessive, and the last eight
# samples, ID[7:0] as the bus showed them, go to the host. 13 words.

        CONFIG open_drain01, 1  # CAN_TX open-drain: the reset 1 lets go, the bus idles recessive
        CONFIG shift_dir, 1     # MSB first: the SOF, then ID[10] down to ID[0]
        PULL                    # {SOF, ID[10:4]} (stalls while the FIFO is empty)
cell:   SHIFT_OUT [5]           # a bit: drive it, a 0 pulls the bus dominant, a 1 lets go, six cycles
        SHIFT_IN 0              #        sample the bus on the seventh, and
        REPEAT 7, cell          #        the eighth: seven bits, the SOF to ID[5]
        SHIFT_OUT [5]           # ID[4], the first byte's last bit, the same cell unrolled
        SHIFT_IN 0              #
        PULL                    #        {ID[3:0], 0000} in the eighth cycle (stalls while the FIFO is empty: the bit stretches)
cell2:  SHIFT_OUT [5]           # ID[3] down to ID[0], the cell again
        SHIFT_IN 0
        REPEAT 4, cell2
        PUSH 0, 1               # let go: recessive, the bus idle; ID[7:0] as sampled to the host
