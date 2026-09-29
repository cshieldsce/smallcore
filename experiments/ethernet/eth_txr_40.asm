# 10BASE-T transmitter at 40 MHz, Manchester from raw host bytes on the core:
# TD on gpio 3, TX_EN on gpio 2, pad 0 a scratch bit read back through its pad.
# 4 clocks a bit, bit 7's block has a PULL too and lasts 5, so one half-bit a byte is 3 clocks: the record of why 40 MHz fails. Each bit is a block in two copies, one per value;
# the SKIP on the next bit, read back from pad 0, picks the next block. No
# frame end: every byte value is data, no count longer than 32 exists, so the
# PULL after the last byte stalls mid-bit with TX_EN high.
# 94 words, 32 distinct.

        SET 2, 0                  # idle
        PULL                      # the first byte
        SHIFT_OUT                 # its bit 0 on the scratch pad
        SHIFT_IN 0                # read back
        SKIP 7, 1
        JMP go0
        SET 3, 0                  # TD = !1 before TX_EN
        JMP go
go0:    SET 3, 1                  # TD = !0 before TX_EN
go:     SKIP 7, 1, 2, 1           # TX_EN high: bit 0's first half from here, two clocks long
        JMP b0v0
        JMP b0v1
b0v0:  SHIFT_OUT 3, 1             # bit 0 = 0: TD = 1; pad 0 = bit 1
        SHIFT_IN 0                # bit 1 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b1v0
        JMP b1v1
b0v1:  SHIFT_OUT 3, 0             # bit 0 = 1: TD = 0; pad 0 = bit 1
        SHIFT_IN 0                # bit 1 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b1v0
        JMP b1v1
b1v0:  SHIFT_OUT 3, 1             # bit 1 = 0: TD = 1; pad 0 = bit 2
        SHIFT_IN 0                # bit 2 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b2v0
        JMP b2v1
b1v1:  SHIFT_OUT 3, 0             # bit 1 = 1: TD = 0; pad 0 = bit 2
        SHIFT_IN 0                # bit 2 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b2v0
        JMP b2v1
b2v0:  SHIFT_OUT 3, 1             # bit 2 = 0: TD = 1; pad 0 = bit 3
        SHIFT_IN 0                # bit 3 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b3v0
        JMP b3v1
b2v1:  SHIFT_OUT 3, 0             # bit 2 = 1: TD = 0; pad 0 = bit 3
        SHIFT_IN 0                # bit 3 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b3v0
        JMP b3v1
b3v0:  SHIFT_OUT 3, 1             # bit 3 = 0: TD = 1; pad 0 = bit 4
        SHIFT_IN 0                # bit 4 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b4v0
        JMP b4v1
b3v1:  SHIFT_OUT 3, 0             # bit 3 = 1: TD = 0; pad 0 = bit 4
        SHIFT_IN 0                # bit 4 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b4v0
        JMP b4v1
b4v0:  SHIFT_OUT 3, 1             # bit 4 = 0: TD = 1; pad 0 = bit 5
        SHIFT_IN 0                # bit 5 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b5v0
        JMP b5v1
b4v1:  SHIFT_OUT 3, 0             # bit 4 = 1: TD = 0; pad 0 = bit 5
        SHIFT_IN 0                # bit 5 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b5v0
        JMP b5v1
b5v0:  SHIFT_OUT 3, 1             # bit 5 = 0: TD = 1; pad 0 = bit 6
        SHIFT_IN 0                # bit 6 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b6v0
        JMP b6v1
b5v1:  SHIFT_OUT 3, 0             # bit 5 = 1: TD = 0; pad 0 = bit 6
        SHIFT_IN 0                # bit 6 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b6v0
        JMP b6v1
b6v0:  SHIFT_OUT 3, 1             # bit 6 = 0: TD = 1; pad 0 = bit 7
        SHIFT_IN 0                # bit 7 read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b7v0
        JMP b7v1
b6v1:  SHIFT_OUT 3, 0             # bit 6 = 1: TD = 0; pad 0 = bit 7
        SHIFT_IN 0                # bit 7 read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b7v0
        JMP b7v1
b7v0:  PULL 3, 1                  # bit 7 = 0: TD = 1; the next byte
        SHIFT_OUT                 # pad 0 = its bit 0
        SHIFT_IN 0                # read back
        SKIP 7, 1, 3, 0           # mid-bit: TD = 0; a 1 next skips
        JMP b0v0
        JMP b0v1
b7v1:  PULL 3, 0                  # bit 7 = 1: TD = 0; the next byte
        SHIFT_OUT                 # pad 0 = its bit 0
        SHIFT_IN 0                # read back
        SKIP 7, 1, 3, 1           # mid-bit: TD = 1; a 1 next skips
        JMP b0v0
        JMP b0v1
