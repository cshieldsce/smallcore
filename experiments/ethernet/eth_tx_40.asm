# 10BASE-T transmitter at 40 MHz, the host's half-bits: 4 clocks a bit, halves of
# 2 and 2. The host sends each data byte as two bytes of Manchester half-bits
# (bit 2i = the first half of data bit i, bit 2i + 1 its second half), the
# preamble and SFD likewise, the FCS it computed likewise, then an end marker
# 0xFF: a first bit cell of two highs, which no data bit is. SHIFT_OUT puts
# one half-bit a word on TD (gpio 0); between two SHIFT_OUTs sits one word:
# TD read back twice for the end marker, RD (gpio_in 1) sampled twice for a
# collision, the PULL, the loop's JMP. Carrier sense before the frame; after
# it TP_IDL, TX_EN (gpio 2) low and a status byte to the host, bit 7 set on a
# collision, which sends the jam and drains the frame's remaining bytes.
# 48 words, 25 distinct.

        CONFIG open_drain01, 2    # RD's pad (1) released; TD (0) push-pull
        SET 2, 0                  # TX_EN low: idle (reset drives every pad high)
frame:  PULL                      # the frame's first host byte; the idle wire waits safely
cs:     SHIFT_IN 1 [1]            # carrier sense: RD four times, 2 clocks apart, a half-bit:
        SHIFT_IN 1 [1]            # a high run is never shorter, so one sample is high
        SHIFT_IN 1 [1]
        SHIFT_IN 1
        SKIP_RUN 4, 0             # all quiet: go
        JMP cs                    # carrier: defer
        JMP s1
top:    SHIFT_OUT                 # S6
        SHIFT_IN 1                # RD
        SHIFT_OUT                 # S7
        SKIP_RUN 2, 0             # RD quiet at both samples: skip the JMP
        JMP collide               # not taken while RD is quiet: costs no clock
        SHIFT_OUT                 # S8
        PULL                      # the next host byte; a stall here breaks the frame
s1:     SHIFT_OUT 2, 1            # S1, and TX_EN (already high after the first)
        SHIFT_IN 0                # S1 back through the pad
        SHIFT_OUT                 # S2
        SHIFT_IN 0                # S2 back
        SHIFT_OUT                 # S3
        SKIP_NORUN 2, 1           # a real bit, S1 != S2: skip the JMP
        JMP end                   # S1 = S2 = 1: the host's end marker, TP_IDL has begun
        SHIFT_OUT                 # S4
        SHIFT_IN 1                # RD
        SHIFT_OUT                 # S5
        JMP top
end:    NOP [4]                   # TP_IDL: TD high since the marker's S1
        SET 2, 0                  # 12 clocks, 300 ns, after the marker: idle
        SHIFT_IN 2                # status: TX_EN read back, 0 = sent
        PUSH                      # to the host: bit 7 of the byte
        JMP frame
collide: SET 0, 1 [1]             # the jam, 32 bits of 0
        SET 0, 0
        REPEAT 32, collide
        SET 0, 1 [10]             # TP_IDL after the jam
        SHIFT_IN 2                # status: TX_EN read back while still high, 1 = collision
        SET 2, 0                  # idle
        PUSH                      # to the host
drain:  PULL                      # the rest of the frame, TX_EN low, up to the end marker
        SHIFT_OUT
        SHIFT_IN 0
        SHIFT_OUT
        SHIFT_IN 0
        SKIP_NORUN 2, 1
        JMP frame                 # the end marker: the next frame
        JMP drain
