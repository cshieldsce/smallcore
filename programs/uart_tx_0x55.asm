# UART 8N1, 0x55 bit-banged with SET, 8 cycles per bit. TX is gpio 0.
# 0x55 = 0b01010101, LSB first: 1 0 1 0 1 0 1 0. Halts after the stop bit
# with the line high.

        SET 0, 1 [7]   # idle (line high)
        SET 0, 0 [7]   # start bit
        SET 0, 1 [7]   # d0
        SET 0, 0 [7]   # d1
        SET 0, 1 [7]   # d2
        SET 0, 0 [7]   # d3
        SET 0, 1 [7]   # d4
        SET 0, 0 [7]   # d5
        SET 0, 1 [7]   # d6
        SET 0, 0 [7]   # d7
        SET 0, 1 [7]   # stop bit
