# SWD host, stage 1: the request alone. One 8-bit request from the TX FIFO,
# LSB first, 8 cycles per bit, and nothing after it: no turnaround, no ACK, no
# data. gpio 0 = SWDIO (the shift pin), 1 = SWCLK.
# The host composes the byte: Start 1, APnDP, RnW, A2, A3, parity of those
# four, Stop 0, Park 1, bit 0 first. The target samples SWDIO on the rising
# edge of SWCLK, so each bit is put on the line while the clock is low and the
# clock is raised over it: spi_tx_lsb.asm's two words per bit with no chip
# select, and no CONFIG because the reset configuration is already SWD's.
# SWDIO idles high and is left high after the park bit, where the turnaround
# will go.

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

        SET 1, 0 [3]        # SWCLK back to idle low
        SET 0, 1            # SWDIO left high: the host still owns the line
