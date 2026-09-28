# programs/swd_read.asm with candidate A, REPEAT count, label, spliced in
# wherever a body repeats: the request's eight cells, the ACK's three, the four
# data bytes of eight. The REPEAT holds one cycle at the end of the body, taken
# from the delay of the word before it, so the wire is the baseline's cycle for
# cycle. 40 words for 103.

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

        SKIP 5, 0                           # OK?    bit 5 clear: step over the JMP
        JMP data                            #        OK: the target keeps the line, the data follows
        PUSH 1, 0 [3]                       # WAIT or FAULT: the ACK to the host as in_shift_reg[7:5]; SWCLK low, the target lets go
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back (push-pull, the 1 on the pin drives again), SWCLK low
        SKIP 6, 0                           # WAIT?  bit 6 clear: step over the JMP
        JMP request                         #        WAIT: the request again, when the host pushes it again
        JMP done                            #        FAULT, or no ACK at all: the PUSH reported it, exit

data:   PUSH 1, 0 [3]                       # OK: the ACK to the host; SWCLK low, data bit 0 is on the line
byte:   SHIFT_IN 0, 1, 1 [3]                # data bit 8k: sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # data bit 8k+1
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+2
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+3
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+4
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+5
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+6
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 8k+7
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [2]                       # data byte k to the host; SWCLK low for 3 cycles, the next bit is on the line, and
        REPEAT 4, byte                      #                          the 4th: four bytes

        SHIFT_IN 0, 1, 1 [3]                # parity: sample SWDIO and SWCLK high; the target lets go after this edge
        PUSH 1, 0 [3]                       # {parity, data[31:25]} to the host; SWCLK low: the turnaround back's low half
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back, SWCLK low
done:
