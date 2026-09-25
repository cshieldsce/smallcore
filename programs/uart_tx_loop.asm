# Continuous UART 8N1 at 8 cycles per bit. TX is gpio 0.
# One frame per FIFO byte, then PULL stalls with the line high until the
# next byte arrives and starts the next frame. JMP costs one idle cycle
# between frames. Never halts.

        SET 0, 1        # idle (line high)
loop:
        PULL 0, 0 [7]   # start bit: shift_reg = next byte (stalls while empty), TX low
        SHIFT_OUT [7]   # d0
        SHIFT_OUT [7]   # d1
        SHIFT_OUT [7]   # d2
        SHIFT_OUT [7]   # d3
        SHIFT_OUT [7]   # d4
        SHIFT_OUT [7]   # d5
        SHIFT_OUT [7]   # d6
        SHIFT_OUT [7]   # d7
        SET 0, 1 [7]    # stop bit
        JMP loop
