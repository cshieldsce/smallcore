# SWD host read: the request, the turnaround, the ACK, the decision, and on OK
# the 32 data bits and the parity the target sends, then the turnaround back.
# swd_request.asm word for word through the third ACK sample; from there the
# decision comes first, because on OK the target keeps the line and drives
# data bit 0 from the very rise the host samples ACK[2] on: no turnaround
# between the ACK and the data, one after the parity. The host reads six
# bytes: the ACK in bits 7:5, the four data bytes from bit 0 up, each whole
# because eight LSB-first samples fill the register end to end, and the
# parity as bit 7 of a fifth byte over data[31:25], the register having
# shifted once more. The core has no XOR: the host checks the parity. The RX
# FIFO holds four bytes and a read is six, so the host pops during the
# transaction, or the fifth PUSH stalls with SWCLK stopped, which SWD allows.
# WAIT and FAULT: the turnaround back, then the request again from the
# host's next byte, or the exit. gpio 0 = SWDIO (the shift pin), 1 = SWCLK.
# 103 words: two per bit, out or in, and a PUSH in place of every eighth
# clock drop; the ISA's repetition pressure at its widest.

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
        SHIFT_IN 0, 1, 1 [3]                # data bit 0: sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # data bit 1
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 2
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 3
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 4
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 5
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 6
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 7
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [3]                       # data byte 0 to the host; SWCLK low, the next bit is on the line
        SHIFT_IN 0, 1, 1 [3]                # data bit 8: sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # data bit 9
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 10
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 11
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 12
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 13
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 14
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 15
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [3]                       # data byte 1 to the host; SWCLK low, the next bit is on the line
        SHIFT_IN 0, 1, 1 [3]                # data bit 16: sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # data bit 17
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 18
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 19
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 20
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 21
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 22
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 23
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [3]                       # data byte 2 to the host; SWCLK low, the next bit is on the line
        SHIFT_IN 0, 1, 1 [3]                # data bit 24: sample SWDIO and SWCLK high on the same edge
        SET 1, 0 [3]                        # data bit 25
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 26
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 27
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 28
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 29
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 30
        SHIFT_IN 0, 1, 1 [3]
        SET 1, 0 [3]                        # data bit 31
        SHIFT_IN 0, 1, 1 [3]
        PUSH 1, 0 [3]                       # data byte 3 to the host; SWCLK low, the parity is on the line
        SHIFT_IN 0, 1, 1 [3]                # parity: sample SWDIO and SWCLK high; the target lets go after this edge
        PUSH 1, 0 [3]                       # {parity, data[31:25]} to the host; SWCLK low: the turnaround back's low half
        SET 1, 1 [3]                        # Turnaround back: SWCLK high, nobody drives
        CONFIG open_drain01, 0, 1, 0 [3]    #             take SWDIO back, SWCLK low
done:
