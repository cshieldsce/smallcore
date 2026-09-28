# programs/swd_read.asm with candidate D, BURST_OUT and BURST_IN, spliced in:
# the request is one burst, each data byte one burst and its PUSH. The ACK's
# three bits and the parity's one stay as they were: a burst is eight. Each
# burst is its eight cells less the last clock word, which is the word after
# it, so the wire is the baseline's cycle for cycle. 33 words for 103.

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
        SHIFT_IN 0, 1, 1 [3]                #         the target puts data bit 0 on the line from this edge if it says OK

        SKIP 5, 0                           # OK?    bit 5 clear: step over the JMP
        JMP data                            #        OK: the target keeps the line, the data follows
        PUSH 1, 0 [3]                       # WAIT or FAULT: the ACK to the host as in_shift_reg[7:5]; SWCLK low, the target lets go
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back (push-pull, the 1 on the pin drives again), SWCLK low
        SKIP 6, 0                           # WAIT?  bit 6 clear: step over the JMP
        JMP request                         #        WAIT: the request again, when the host pushes it again
        JMP done                            #        FAULT, or no ACK at all: the PUSH reported it, exit

data:   PUSH 1, 0 [3]                       # OK: the ACK to the host; SWCLK low, data bit 0 is on the line
        BURST_IN 0, 1, 1 [3]                # data bits 0..7: sample SWDIO and SWCLK high, then SWCLK low, eight times, the eighth low left to
        PUSH 1, 0 [3]                       # data byte 0 to the host; SWCLK low, the next bit is on the line
        BURST_IN 0, 1, 1 [3]                # data bits 8..15
        PUSH 1, 0 [3]                       # data byte 1 to the host
        BURST_IN 0, 1, 1 [3]                # data bits 16..23
        PUSH 1, 0 [3]                       # data byte 2 to the host
        BURST_IN 0, 1, 1 [3]                # data bits 24..31
        PUSH 1, 0 [3]                       # data byte 3 to the host; SWCLK low, the parity is on the line

        SHIFT_IN 0, 1, 1 [3]                # parity: sample SWDIO and SWCLK high; the target lets go after this edge
        PUSH 1, 0 [3]                       # {parity, data[31:25]} to the host; SWCLK low: the turnaround back's low half
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back, SWCLK low
done:
