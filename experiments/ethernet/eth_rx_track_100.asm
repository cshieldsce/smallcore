# 10BASE-T receiver at 100 MHz re-aligning on every mid-bit edge, 10 clocks a
# bit: the sample 6 clocks after the edge, the WAIT up 1 clock(s)
# before the next. Each bit's first half, the complement of the bit, is sampled
# and picks WAIT 0, 1 or WAIT 0, 0 for the edge at its mid-bit; the WAIT
# issues on it. The byte pushed is the data inverted. The preamble and SFD
# are found at fixed timing as eth_rx_fixed does. RD on gpio_in 0. Runs
# forever. 58 words, 27 distinct.

        CONFIG open_drain01, 1    # pad 0 released: RD
        WAIT 0, 0
        WAIT 0, 1                 # a preamble rise: m
hunt:   SHIFT_IN 0                # m + 1: the bit, from its second half
        SKIP_RUN 2, 1             # 1 1: the SFD's end
        JMP hunt [7]
        NOP [2]                   # to bit 0's first half, m + 6
c0:     SHIFT_IN 0                # bit 0's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f0                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 1
c1:     SHIFT_IN 0                # bit 1's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f1                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 2
c2:     SHIFT_IN 0                # bit 2's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f2                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 3
c3:     SHIFT_IN 0                # bit 3's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f3                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 4
c4:     SHIFT_IN 0                # bit 4's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f4                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 5
c5:     SHIFT_IN 0                # bit 5's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f5                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 6
c6:     SHIFT_IN 0                # bit 6's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f6                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1 [5]             # the rise: m, then on into bit 7
c7:     SHIFT_IN 0                # bit 7's first half: its complement
        SKIP 7, 0                 # a 0 there: the bit is 1, a rise at mid-bit
        JMP f7                    # a 1: a fall, its WAIT a clock later
        WAIT 0, 1                 # the rise: m
        PUSH [3]                  # the byte, inverted
        JMP c0
f7:     WAIT 0, 0                 # the fall: m
        PUSH [3]
        JMP c0
f0:     WAIT 0, 0 [4]             # the fall: m
        JMP c1
f1:     WAIT 0, 0 [4]             # the fall: m
        JMP c2
f2:     WAIT 0, 0 [4]             # the fall: m
        JMP c3
f3:     WAIT 0, 0 [4]             # the fall: m
        JMP c4
f4:     WAIT 0, 0 [4]             # the fall: m
        JMP c5
f5:     WAIT 0, 0 [4]             # the fall: m
        JMP c6
f6:     WAIT 0, 0 [4]             # the fall: m
        JMP c7
