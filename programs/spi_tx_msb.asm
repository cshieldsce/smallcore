# SPI mode 0 master transmit of one byte from the TX FIFO, MSB first, 8 CPU cycles per bit.
#
# Pins: gpio 0 = MOSI (SHIFT_OUT always drives gpio 0), gpio 1 = SCLK, gpio 2 = CS.
# Mode 0: SCLK idles low, MOSI changes while SCLK is low, the slave samples
# MOSI on the rising edge. CS is active low and frames the eight clocks.
#
# Every pin resets high, so the clock is taken to idle low before CS falls.
# Each bit is two instructions: SHIFT_OUT puts the next bit on MOSI and drops
# the clock on the same edge (its GPIO side effect), then SET raises the clock.
# 4 cycles low, 4 cycles high.
#
# Bit order is machine configuration, not part of SHIFT_OUT: CONFIG shift_dir, 1
# makes every SHIFT_OUT send shift_reg[7] and shift left, so the frame goes
# out MSB first, as most SPI devices expect. The eight SHIFT_OUTs below are
# the same words as in spi_tx_lsb.asm; only the configuration differs.

        CONFIG shift_dir, 1 # MSB first
        SET 1, 0            # SCLK idle low
        PULL 2, 0 [3]       # shift_reg = byte to send (stalls here while the FIFO is empty)
                            # and CS low on the edge the byte arrives: start of frame

        SHIFT_OUT 1, 0 [3]  # bit 7: MOSI = next bit, SCLK low
        SET 1, 1 [3]        #        SCLK high, slave samples
        SHIFT_OUT 1, 0 [3]  # bit 6
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 5
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 4
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 3
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 2
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 1
        SET 1, 1 [3]
        SHIFT_OUT 1, 0 [3]  # bit 0
        SET 1, 1 [3]

        SET 1, 0 [3]        # clock back to idle low
        SET 2, 1            # CS high: end of frame
