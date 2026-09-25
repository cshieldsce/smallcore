# UART 8N1 receiver, 8 cycles per bit. RX is gpio_in 0.
# WAIT holds the loop while the line idles high and issues on the cycle the
# start bit falls; its delay then covers the start bit and half of d0, so the
# eight SHIFT_INs sample the data bits mid-bit, 12 + 8 i cycles after the
# edge. PUSH hands the byte over during the stop bit, JMP is back at the WAIT
# 80 cycles after the edge, in time for a frame that follows back to back.
# Any idle between frames is spent in the WAIT. Never halts.

loop:
        WAIT 0, 0 [11]  # start bit: hold until RX falls, then skip it and half of d0
        SHIFT_IN 0 [7]  # d0, 12 cycles after the start bit
        SHIFT_IN 0 [7]  # d1
        SHIFT_IN 0 [7]  # d2
        SHIFT_IN 0 [7]  # d3
        SHIFT_IN 0 [7]  # d4
        SHIFT_IN 0 [7]  # d5
        SHIFT_IN 0 [7]  # d6
        SHIFT_IN 0 [7]  # d7
        PUSH [2]        # rx_fifo <- the byte, mid stop bit (stalls if the host is behind)
        JMP loop        # 80 cycles after the start bit: the next one may fall now
