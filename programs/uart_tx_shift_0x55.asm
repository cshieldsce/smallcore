# UART 8N1 transmit of 0x55 at 8 CPU cycles per bit, using the shift register.
#
# Same frame as uart_tx_0x55.asm, but the data bits come from the shift
# register instead of eight hand-written SETs: LOAD fills it, and each
# SHIFT_OUT [7] drives one bit (LSB first) and holds it for 1 + 7 = 8 cycles.
# Start and stop bits are still plain SETs.

        LOAD 0x55       # shift_reg = 0b01010101, d0 in bit 0 (pin unchanged)
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
