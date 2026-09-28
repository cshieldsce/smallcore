# programs/uart_tx_loop.asm with REPEAT: 6 words for 12.
        SET 0, 1        # idle (line high)
loop:
        PULL 0, 0 [7]   # start bit: shift_reg = next byte (stalls while empty), TX low
bit:    SHIFT_OUT [6]   # d0..d7, 7 cycles each, and
        REPEAT 8, bit   # the 8th
        SET 0, 1 [7]    # stop bit
        JMP loop
