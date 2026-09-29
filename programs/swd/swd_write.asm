# SWD host write: the request, the turnaround, the ACK, the decision, and on OK,
# after the turnaround back, the 32 data bits and the parity from the host.
# swd_read.asm word for word through the third ACK sample; from there the
# turnaround back comes first, because the host owns the line for the data
# whatever the answer: WAIT and FAULT need it back too. The host queues the
# request, and only after it has read the OK the four data bytes from bit 0 up
# and a fifth byte with the parity in bit 0: the core has no XOR, and a byte
# queued behind the request would be PULLed as the request on a WAIT retry,
# there being no way to discard a queued byte but PULLing it. Each data byte's
# PULL sits in the last high cycle of the clock before it, so a prompt host
# costs no cycles; an empty FIFO stalls the PULL with SWCLK held, which SWD
# allows. gpio 0 = SWDIO (the shift pin), 1 = SWCLK.
# 106 words: two per bit, out or in; the ISA's repetition pressure again.

        SET 1, 0            # SWCLK idle low (every pin resets high)
request: PULL [3]           # shift_reg = the request (stalls while the FIFO is empty)

        SHIFT_OUT 1, 0 [3]  # Start:  SWDIO = the bit, SWCLK low
        SET 1, 1 [3]        #         SWCLK high, the target samples
        SHIFT_OUT 1, 0 [3]  # APnDP
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # RnW
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # A2
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # A3
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # Parity
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # Stop
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # Park
        SET 1, 1 [3]

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
        SHIFT_OUT 1, 0 [3]  # data bit 0: SWDIO = the bit, SWCLK low
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 1
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 2
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 3
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 4
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 5
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 6
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 7
        SET 1, 1 [2]                        #          SWCLK high for 3 cycles, and
        PULL                                # data byte 1 in the 4th: the beat holds while the host is prompt
        SHIFT_OUT 1, 0 [3]  # data bit 8: SWDIO = the bit, SWCLK low
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 9
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 10
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 11
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 12
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 13
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 14
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 15
        SET 1, 1 [2]                        #          SWCLK high for 3 cycles, and
        PULL                                # data byte 2 in the 4th: the beat holds while the host is prompt
        SHIFT_OUT 1, 0 [3]  # data bit 16: SWDIO = the bit, SWCLK low
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 17
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 18
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 19
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 20
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 21
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 22
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 23
        SET 1, 1 [2]                        #          SWCLK high for 3 cycles, and
        PULL                                # data byte 3 in the 4th: the beat holds while the host is prompt
        SHIFT_OUT 1, 0 [3]  # data bit 24: SWDIO = the bit, SWCLK low
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 25
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 26
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 27
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 28
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 29
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 30
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # data bit 31
        SET 1, 1 [2]                        #          SWCLK high for 3 cycles, and
        PULL                                # the parity byte in the 4th: the beat holds while the host is prompt
        SHIFT_OUT 1, 0 [3]                  # parity: SWDIO = bit 0 of the fifth byte, SWCLK low
        SET 1, 1 [3]                        #         SWCLK high, the target samples
        SET 1, 0 [3]                        # SWCLK back to idle low; the host keeps the line
done:
