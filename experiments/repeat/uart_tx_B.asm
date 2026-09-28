# programs/uart_tx_pull.asm with candidate B, REPEAT_NEXT count: the one place
# in the repo a bit cell is one word. The REPEAT_NEXT's cycle comes out of the
# start bit's delay. 5 words for 11. SWD's cells are two words: B has nothing
# to offer them.

        SET 0, 1 [7]    # idle (line high)
        PULL 0, 0 [6]   # start bit: shift_reg = the FIFO byte, TX low, 7 cycles, and
        REPEAT_NEXT 8   #            the 8th: eight of
        SHIFT_OUT [7]   # d0..d7
        SET 0, 1 [7]    # stop bit
