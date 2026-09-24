# UART 8N1 transmit of one byte from the TX FIFO at 8 CPU cycles per bit.
#
# Same frame as uart_tx_0x55.asm, but the data comes from outside the
# program: PULL moves the next FIFO byte into the shift register, so this one
# program sends whatever byte the FIFO holds (CPU(program, tx_data=[0xA3])).

        PULL            # shift_reg = next FIFO byte, d0 in bit 0 (pin unchanged)
        SET 1 [7]       # idle (line high)
        SET 0 [7]       # start bit
        SHIFT_OUT [7]   # d0
        SHIFT_OUT [7]   # d1
        SHIFT_OUT [7]   # d2
        SHIFT_OUT [7]   # d3
        SHIFT_OUT [7]   # d4
        SHIFT_OUT [7]   # d5
        SHIFT_OUT [7]   # d6
        SHIFT_OUT [7]   # d7
        SET 1 [7]       # stop bit
