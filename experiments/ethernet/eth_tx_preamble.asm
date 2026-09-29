# 10BASE-T stage 3: the preamble (7 x 0x55) and the SFD (0xD5), LSB first, from
# the program alone at 40 MHz: the 62 alternating bits are one REPEAT of a
# two-word pair, the SFD's closing 1 1 written out. 10 words. Halts.

        SET 2, 0                  # idle
        SET 0, 0                  # TD low: bit 0 is a 1, its first half low
        SET 2, 1 [1]              # TX_EN: the first half of bit 0
pair:   SET 0, 1 [3]              # mid-bit rise of a 1: its second half, the first half of the 0 after it
        SET 0, 0 [2]              # mid-bit fall of the 0: its second half, the first half of the next 1
        REPEAT 31, pair           # 31 pairs: bits 0..61, and the first half of bit 62
        SET 0, 1 [1]              # bit 62, the SFD's seventh, a 1: second half
        SET 0, 0 [1]              # bit 63, a 1: first half
        SET 0, 1 [13]             # its second half, then TP_IDL held high three bit times
        SET 2, 0                  # idle
