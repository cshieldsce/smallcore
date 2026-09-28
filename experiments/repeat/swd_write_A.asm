# programs/swd_write.asm with candidate A, REPEAT count, label, spliced in: the
# request's eight cells, the ACK's three, the four data bytes. Each REPEAT's
# cycle comes out of the delay before it. The data loop starts with the byte's
# PULL, so the loop word sits before the PULL and the PULL keeps the 4th high
# cycle: a stalling word at the end of a body, just before the loop word, would
# start its stall a cycle early and end a cycle late. 40 words for 106.

        SET 1, 0            # SWCLK idle low (every pin resets high)
request: PULL [3]           # shift_reg = the request (stalls while the FIFO is empty)

req:    SHIFT_OUT 1, 0 [3]  # a request bit: SWDIO = the bit, SWCLK low
        SET 1, 1 [2]        #                SWCLK high for 3 cycles, the target samples, and
        REPEAT 8, req       #                the 4th: eight bits, Start to Park

        CONFIG open_drain01, 1, 1, 0 [3]    # Turnaround: let go of SWDIO (open-drain with the park's 1), SWCLK low
        SET 1, 1 [3]                        #             SWCLK high: nobody drives, the target takes the line after this edge
ack:    SET 1, 0 [3]                        # an ACK bit: SWCLK low, the target's bit is on the line
        SHIFT_IN 0, 1, 1 [2]                #             sample SWDIO and SWCLK high on the same edge, 3 cycles, and
        REPEAT 3, ack                       #             the 4th: three bits
        PUSH 1, 0 [3]                       # SWCLK low, the target lets go; the ACK to the host as in_shift_reg[7:5]
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back (push-pull, the 1 on the pin drives again), SWCLK low

        SKIP 5, 0                           # OK?    bit 5 clear: step over the JMP
        JMP data                            #        OK: the data, once the host has queued it
        SKIP 6, 0                           # WAIT?  bit 6 clear: step over the JMP
        JMP request                         #        WAIT: the request again, when the host pushes it again
        JMP done                            #        FAULT, or no ACK at all: the PUSH reported it, exit

data:   PULL                                # data byte k (stalls while the FIFO is empty: SWCLK low before byte 0, high before the others)
        SHIFT_OUT 1, 0 [3]  # data bit 8k: SWDIO = the bit, SWCLK low
        SET 1, 1 [3]        #              SWCLK high, the target samples
        SHIFT_OUT 1, 0 [3]  # data bit 8k+1
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+2
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+3
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+4
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+5
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+6
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 8k+7
        SET 1, 1 [1]                        #              SWCLK high for 2 cycles,
        REPEAT 4, data                      #              the 3rd: back for the next byte, four in all, and
        PULL                                # the parity byte in the 4th high cycle (stalls while the FIFO is empty, SWCLK high)

        SHIFT_OUT 1, 0 [3]                  # parity: SWDIO = bit 0 of the fifth byte, SWCLK low
        SET 1, 1 [3]                        #         SWCLK high, the target samples
        SET 1, 0 [3]                        # SWCLK back to idle low; the host keeps the line
done:
