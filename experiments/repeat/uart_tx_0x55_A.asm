# programs/uart_tx_0x55.asm with REPEAT: the frame 1 0 1 0 1 0 1 0 1 0 1 is a
# pair five times and a one. 4 words for 11, the same 88 cycles.
pair:   SET 0, 1 [7]    # idle, then d0, d2, d4, d6: high 8 cycles
        SET 0, 0 [6]    # start, then d1, d3, d5, d7: low 7 cycles, and
        REPEAT 5, pair  # the 8th
        SET 0, 1 [7]    # stop bit
