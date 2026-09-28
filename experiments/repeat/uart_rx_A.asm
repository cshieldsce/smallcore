# programs/uart_rx.asm with REPEAT: 6 words for 12.
        CONFIG open_drain01, 1  # RX is a pad we listen on: pin 0 open-drain, released
loop:
        WAIT 0, 0 [11]  # start bit: hold until RX falls, then skip it and half of d0
bit:    SHIFT_IN 0 [6]  # d0..d7, 7 cycles each, and
        REPEAT 8, bit   # the 8th: the next sample 8 cycles after the last
        PUSH [2]        # rx_fifo <- the byte, mid stop bit (stalls if the host is behind)
        JMP loop        # 80 cycles after the start bit: the next one may fall now
