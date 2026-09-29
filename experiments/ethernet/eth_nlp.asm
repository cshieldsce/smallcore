# 10BASE-T normal link pulses at 40 MHz: TX_EN (gpio 2) high for 100 ns with TD
# high, about every 16 ms. The core cannot count past 32 and REPEAT does not
# nest, so the long wait is an inner REPEAT and a Johnson counter kept in
# in_shift_reg through pad 3 (a scratch pad read back). Idle only: a program
# waiting for the host can only stall on PULL, which stops the pulses.
# 51 words.

        SET 2, 0                  # idle
        SET 0, 1                  # TD high: a pulse is TX_EN with TD high
pulse:  SET 2, 1 [3]              # the link pulse, 100 ns
        SET 2, 0                  # idle
wait:   NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        NOP [31]
        REPEAT 32, wait           # 32 x (32 x inner + 1) clocks
        SET 3, 0                  # the Johnson step: pad 3 = NOT the oldest sample
        SKIP 0, 1
        SET 3, 1
        SHIFT_IN 3                # read back: the newest sample
        SKIP_RUN 8, 1             # all ones: once in 16 steps
        JMP wait
        JMP pulse
