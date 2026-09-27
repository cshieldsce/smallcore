# SWD host, stages 1 to 4: the request, the turnaround, the ACK, the decision.
# One 8-bit request from the TX FIFO, LSB first, 8 cycles per bit; the host
# lets go of SWDIO for one clock and the target takes the line; the host
# samples the three ACK bits on the next three clocks and PUSHes them; one
# more clock with nobody driving and the host takes the line back; then OK
# goes on (to where the data phase will be), WAIT sends the request again,
# when the host supplies it again, FAULT exits, the PUSH having reported it.
# No data yet. gpio 0 = SWDIO (the shift pin), 1 = SWCLK.
# The host composes the byte: Start 1, APnDP, RnW, A2, A3, parity of those
# four, Stop 0, Park 1, bit 0 first. The target samples SWDIO on the rising
# edge of SWCLK, so each bit is put on the line while the clock is low and the
# clock is raised over it: spi_tx_lsb.asm's two words per bit with no chip
# select, and no CONFIG shift_dir because the reset configuration is SWD's.
# Letting go is the pad mode: CONFIG makes SWDIO open-drain, and the 1 the
# park bit left on it is what an open-drain pin does not drive; CONFIG back
# to push-pull drives that 1 again. Both words drop SWCLK too, so each
# turnaround is the line let go or taken as a clock falls and one clock with
# nobody driving. The target drives ACK[0] from the first turnaround's rising
# edge; each ACK bit is on the line through the low half that follows and is
# sampled on the edge that raises SWCLK, as I2C's ACK is. LSB first, a sample
# enters at bit 7 and walks right: three of them leave the ACK in bits 7:5,
# the host reads OK as 0x20, WAIT as 0x40 and FAULT as 0x80, and SKIP looks
# at bit 5 then bit 6. SKIP sees one bit at a time, so the three-way decision
# is two SKIPs and three JMPs. WAIT cannot resend from here: SHIFT_OUT emptied
# shift_reg and only PULL reloads it, so the retry is a JMP to the PULL and the
# host pushes the request again. A second ACK shifts in above the first, which
# walks down to bits 4:2; the host reads the ACK as the byte >> 5 either way.

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
        JMP data                            #        OK: on to the data phase
        SKIP 6, 0                           # WAIT?  bit 6 clear: step over the JMP
        JMP request                         #        WAIT: the request again, when the host pushes it again
        JMP done                            #        FAULT, or no ACK at all: the PUSH reported it, exit
data:                                       # the data phase will go here
done:
