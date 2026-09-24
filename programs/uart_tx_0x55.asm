# UART 8N1 transmit of 0x55 at 8 CPU cycles per bit. TX is gpio 0.
#
# Each bit is one SET of pin 0 with a delay of 7: 1 + 7 = 8 cycles.
# 0x55 = 0b01010101, sent LSB first: 1 0 1 0 1 0 1 0
# The program ends after the stop bit, which halts the CPU with the line high.

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
