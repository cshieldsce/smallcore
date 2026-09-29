# 10BASE-T transmitter at 20 MHz, the host's half-bits, one clock a half-bit:
# there is no free clock for the PULL or the JMP, so the last half-bit of every
# host byte lasts three clocks, not one. Kept as the record of why 20 MHz
# fails: 10 clocks for 8 half-bits. No end marker, no carrier sense.
# 11 words.

        SET 2, 0                  # idle
top:    PULL                      # a host byte of half-bits
        SHIFT_OUT 2, 1            # S1 and TX_EN
        SHIFT_OUT                 # S2
        SHIFT_OUT                 # S3
        SHIFT_OUT                 # S4
        SHIFT_OUT                 # S5
        SHIFT_OUT                 # S6
        SHIFT_OUT                 # S7
        SHIFT_OUT                 # S8: held three clocks, through the JMP and the PULL
        JMP top
