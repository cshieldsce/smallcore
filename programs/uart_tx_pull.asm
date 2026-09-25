# UART 8N1, one byte from the TX FIFO, 8 cycles per bit. TX is gpio 0.
# The same frame as uart_tx_0x55.asm for any byte: PULL loads the shift
# register and drops TX for the start bit on the same edge, SHIFT_OUT sends
# the data bits LSB first (shift_dir resets to 0).

        SET 0, 1 [7]    # idle (line high)
        PULL 0, 0 [7]   # start bit: shift_reg = the FIFO byte, TX low
        SHIFT_OUT [7]   # d0
        SHIFT_OUT [7]   # d1
        SHIFT_OUT [7]   # d2
        SHIFT_OUT [7]   # d3
        SHIFT_OUT [7]   # d4
        SHIFT_OUT [7]   # d5
        SHIFT_OUT [7]   # d6
        SHIFT_OUT [7]   # d7
        SET 0, 1 [7]    # stop bit
