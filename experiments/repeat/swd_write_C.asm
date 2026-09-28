# programs/swd_write.asm with candidate C, LOAD count and DJNZ label, spliced
# in: the request, the ACK, the data bytes. The data loop's LOAD sits on the
# common path after the ACK, where a delay had a cycle to give: on WAIT or
# FAULT the count is simply never used. The data loop starts with the byte's
# PULL so the PULL keeps its 4th high cycle (see swd_write_A.asm). Cycle for
# cycle the baseline's wire. 43 words for 106.

        SET 1, 0            # SWCLK idle low (every pin resets high)
request: PULL [2]           # shift_reg = the request (stalls while the FIFO is empty), 3 cycles, and
        LOAD 8              # the 4th: eight request bits to go
req:    SHIFT_OUT 1, 0 [3]  # a request bit: SWDIO = the bit, SWCLK low
        SET 1, 1 [2]        #                SWCLK high for 3 cycles, the target samples, and
        DJNZ req            #                the 4th: the next bit while any are left

        CONFIG open_drain01, 1, 1, 0 [3]    # Turnaround: let go of SWDIO (open-drain with the park's 1), SWCLK low
        SET 1, 1 [2]                        #             SWCLK high: nobody drives, the target takes the line after this edge, and
        LOAD 3                              #             in the 4th cycle: three ACK bits to go
ack:    SET 1, 0 [3]                        # an ACK bit: SWCLK low, the target's bit is on the line
        SHIFT_IN 0, 1, 1 [2]                #             sample SWDIO and SWCLK high on the same edge, 3 cycles, and
        DJNZ ack                            #             the 4th: the next bit while any are left
        PUSH 1, 0 [2]                       # SWCLK low, the target lets go; the ACK to the host as in_shift_reg[7:5], 3 cycles, and
        LOAD 4                              # the 4th: four data bytes to go, should the ACK be OK
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
        DJNZ data                           #              the 3rd: back for the next byte while any are left, and
        PULL                                # the parity byte in the 4th high cycle (stalls while the FIFO is empty, SWCLK high)

        SHIFT_OUT 1, 0 [3]                  # parity: SWDIO = bit 0 of the fifth byte, SWCLK low
        SET 1, 1 [3]                        #         SWCLK high, the target samples
        SET 1, 0 [3]                        # SWCLK back to idle low; the host keeps the line
done:
