# Continuous UART 8N1 transmit at 8 CPU cycles per bit.
#
# Sends every byte in the TX FIFO, one frame each, then waits: PULL stalls
# on the empty FIFO with the line still high from the stop bit, and the next
# byte pushed in starts the next frame. The program never halts.
#
# JMP and a successful PULL each take one cycle, so there are two extra
# idle-high cycles between frames. UART allows any idle time between frames.

        SET 1           # idle (line high)
loop:
        PULL            # shift_reg = next FIFO byte (stalls here while empty)
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
        JMP loop
