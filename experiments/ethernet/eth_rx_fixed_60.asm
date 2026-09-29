# 10BASE-T receiver at 60 MHz with fixed sampling: one WAIT for a preamble rise,
# then every bit sampled one clock after where its mid-bit edge should be, 6
# clocks a bit, never re-aligned; the SFD is the first two 1s in a row. RD on
# gpio_in 0. Runs forever: the frame's end is the carrier going away, which
# nothing waits for. 12 words.

        CONFIG open_drain01, 1    # pad 0 released: RD
        WAIT 0, 0                 # quiet or a low half
        WAIT 0, 1                 # a rise: the preamble's mid-bit of a 1 (m)
hunt:   SHIFT_IN 0                # the second half of the bit, m + 1: the bit
        SKIP_RUN 2, 1             # 1 1: the SFD's end
        JMP hunt [3]
        NOP [3]                   # the SFD found: on to bit 0's sample
data:   SHIFT_IN 0 [4]            # bits 0..6, one sample every 6 clocks
        REPEAT 7, data
        SHIFT_IN 0 [3]            # bit 7
        PUSH                      # the byte, LSB first
        JMP data
