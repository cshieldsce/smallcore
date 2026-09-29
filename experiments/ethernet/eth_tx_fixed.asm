# 10BASE-T stage 1: the byte 0xa5 Manchester-encoded, LSB first, at
# 40 MHz (2 + 2 clocks a bit), every half-bit a SET on TD (gpio 0), TX_EN
# (gpio 2) high around it, then TP_IDL and idle. 20 words. Halts.

        SET 2, 0                  # TX_EN low: the wire idle (reset drives every pad high)
        SET 0, 0                  # TD at the first half of bit 0 while still idle
        SET 2, 1 [1]              # TX_EN: the first half of bit 0, TD already there
        SET 0, 1 [1]              # bit 0 second half
        SET 0, 1 [1]              # bit 1 first half
        SET 0, 0 [1]              # bit 1 second half
        SET 0, 0 [1]              # bit 2 first half
        SET 0, 1 [1]              # bit 2 second half
        SET 0, 1 [1]              # bit 3 first half
        SET 0, 0 [1]              # bit 3 second half
        SET 0, 1 [1]              # bit 4 first half
        SET 0, 0 [1]              # bit 4 second half
        SET 0, 0 [1]              # bit 5 first half
        SET 0, 1 [1]              # bit 5 second half
        SET 0, 1 [1]              # bit 6 first half
        SET 0, 0 [1]              # bit 6 second half
        SET 0, 0 [1]              # bit 7 first half
        SET 0, 1 [1]              # bit 7 second half
        SET 0, 1 [11]             # TP_IDL: high for three bit times, 300 ns
        SET 2, 0                  # idle
