# SPI mode 0 master, one byte from the TX FIFO, LSB first, 8 cycles per bit.
# gpio 0 = MOSI (the shift pin), 1 = SCLK, 2 = CS (active low).
# Mode 0: SCLK idles low, MOSI changes while it is low, the slave samples on
# the rising edge. Two instructions per bit: SHIFT_OUT puts the next bit on
# MOSI and drops the clock on the same edge, SET raises it, 4 cycles each.
# Bit order is configuration: spi_tx_msb.asm differs only in its CONFIG.

        CONFIG shift_dir, 0 # LSB first (the reset value)
        SET 1, 0            # SCLK idle low (every pin resets high)
        PULL 2, 0 [3]       # shift_reg = the byte (stalls while the FIFO is empty),
                            # CS low on the edge it arrives: start of frame

        SHIFT_OUT 1, 0 [3]  # bit 0: MOSI = next bit, SCLK low
        SET 1, 1 [3]        #        SCLK high, slave samples
        SHIFT_OUT 1, 0 [3]  # bit 1
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 2
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 3
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 4
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 5
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 6
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 7
        SET 1, 1 [3]

        SET 1, 0 [3]        # clock back to idle low
        SET 2, 1            # CS high: end of frame
