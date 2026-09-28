# programs/uart_tx_pull.asm with candidate D, BURST_OUT: the eight data bits
# from one word, no side effect, each cell a shift half and an empty return
# half of 4 cycles. The eighth return is the stop bit's word, which grows by
# 4 cycles to keep the frame. 4 words for 11.

        SET 0, 1 [7]    # idle (line high)
        PULL 0, 0 [7]   # start bit: shift_reg = the FIFO byte, TX low
        BURST_OUT [3]   # d0..d7, 8 cycles each: 4 shifted, 4 held, the eighth hold being
        SET 0, 1 [11]   # the stop bit's first 4 cycles, then the stop bit
