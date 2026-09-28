# programs/uart_tx_pull.asm with REPEAT: 5 words for 11.
        SET 0, 1 [7]    # idle (line high)
        PULL 0, 0 [7]   # start bit: shift_reg = the FIFO byte, TX low
bit:    SHIFT_OUT [6]   # d0..d7, 7 cycles each, and
        REPEAT 8, bit   # the 8th
        SET 0, 1 [7]    # stop bit
