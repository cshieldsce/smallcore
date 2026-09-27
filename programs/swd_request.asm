# SWD host, stages 1 and 2: the request and the turnaround. One 8-bit request
# from the TX FIFO, LSB first, 8 cycles per bit, then the host lets go of
# SWDIO for one clock so the target can take the line. No ACK, no data yet.
# gpio 0 = SWDIO (the shift pin), 1 = SWCLK.
# The host composes the byte: Start 1, APnDP, RnW, A2, A3, parity of those
# four, Stop 0, Park 1, bit 0 first. The target samples SWDIO on the rising
# edge of SWCLK, so each bit is put on the line while the clock is low and the
# clock is raised over it: spi_tx_lsb.asm's two words per bit with no chip
# select, and no CONFIG shift_dir because the reset configuration is SWD's.
# Letting go is the pad mode: CONFIG makes SWDIO open-drain, and the 1 the
# park bit left on it is what an open-drain pin does not drive. The same word
# drops SWCLK, so the line is let go as the park bit's clock falls, and one
# more clock, the turnaround, finds nobody driving.

        SET 1, 0            # SWCLK idle low (every pin resets high)
        PULL [3]            # shift_reg = the request (stalls while the FIFO is empty)

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
        SET 1, 0 [3]                        # SWCLK back to idle low, SWDIO still let go
