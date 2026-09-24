# SPI mode 0 master transmit of one byte from the TX FIFO, 9 CPU cycles per bit.
#
# Pins: gpio 0 = MOSI (SHIFT_OUT always drives gpio 0), gpio 1 = SCLK, gpio 2 = CS.
# Mode 0: SCLK idles low, MOSI changes while SCLK is low, the slave samples
# MOSI on the rising edge. CS is active low and frames the eight clocks.
#
# Every pin resets high, so the clock is taken to idle low before CS falls.
# Each bit is three instructions: clock low, next bit onto MOSI, clock high.
# That makes the low half 5 cycles and the high half 4: SPI does not mind.
# SHIFT_OUT sends LSB first, so this is an LSB-first SPI frame.

        SET 1, 0        # SCLK idle low
        PULL            # shift_reg = byte to send (stalls here while the FIFO is empty)
        SET 2, 0 [3]    # CS low: start of frame

        SET 1, 0        # bit 0: clock low
        SHIFT_OUT [3]   #        MOSI = next bit
        SET 1, 1 [3]    #        clock high, slave samples
        SET 1, 0        # bit 1
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 2
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 3
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 4
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 5
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 6
        SHIFT_OUT [3]
        SET 1, 1 [3]
        SET 1, 0        # bit 7
        SHIFT_OUT [3]
        SET 1, 1 [3]

        SET 1, 0 [3]    # clock back to idle low
        SET 2, 1        # CS high: end of frame
