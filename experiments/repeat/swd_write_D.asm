# programs/swd_write.asm with candidate D, BURST_OUT and BURST_IN, spliced in:
# the request is one burst, each data byte one burst, its clock word and its
# PULL. The ACK's three bits and the parity's one stay as they were: a burst is
# eight. Cycle for cycle the baseline's wire. 36 words for 106.

        SET 1, 0            # SWCLK idle low (every pin resets high)
request: PULL [3]           # shift_reg = the request (stalls while the FIFO is empty)

        BURST_OUT 1, 0 [3]  # Start to Park: SWDIO = the bit and SWCLK low, then SWCLK high, eight times, the eighth high left to
        SET 1, 1 [3]        #                SWCLK high, the target samples the Park bit

        CONFIG open_drain01, 1, 1, 0 [3]    # Turnaround: let go of SWDIO (open-drain with the park's 1), SWCLK low
        SET 1, 1 [3]                        #             SWCLK high: nobody drives, the target takes the line after this edge
        SET 1, 0 [3]                        # ACK[0]: SWCLK low, the target's bit is on the line
        SHIFT_IN 0, 1, 1 [3]                #         sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # ACK[1]
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # ACK[2]
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [3]                       # SWCLK low, the target lets go; the ACK to the host as in_shift_reg[7:5]
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back (push-pull, the 1 on the pin drives again), SWCLK low

        SKIP 5, 0                           # OK?    bit 5 clear: step over the JMP
        JMP data                            #        OK: the data, once the host has queued it
        SKIP 6, 0                           # WAIT?  bit 6 clear: step over the JMP
        JMP request                         #        WAIT: the request again, when the host pushes it again
        JMP done                            #        FAULT, or no ACK at all: the PUSH reported it, exit

data:   PULL                                # data byte 0 (stalls while the FIFO is empty, SWCLK low)
        BURST_OUT 1, 0 [3]                  # data bits 0..7: SWDIO = the bit and SWCLK low, then SWCLK high, eight times, the eighth high left to
        SET 1, 1 [2]                        #                 SWCLK high for 3 cycles, and
        PULL                                # data byte 1 in the 4th: the beat holds while the host is prompt
        BURST_OUT 1, 0 [3]                  # data bits 8..15
        SET 1, 1 [2]
        PULL                                # data byte 2
        BURST_OUT 1, 0 [3]                  # data bits 16..23
        SET 1, 1 [2]
        PULL                                # data byte 3
        BURST_OUT 1, 0 [3]                  # data bits 24..31
        SET 1, 1 [2]
        PULL                                # the parity byte

        SHIFT_OUT 1, 0 [3]                  # parity: SWDIO = bit 0 of the fifth byte, SWCLK low
        SET 1, 1 [3]                        #         SWCLK high, the target samples
        SET 1, 0 [3]                        # SWCLK back to idle low; the host keeps the line
done:
