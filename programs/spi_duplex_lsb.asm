# SPI mode 0 master full-duplex transfer of one byte, LSB first, 8 CPU cycles per bit.
#
# Pins: gpio 0 = MOSI (SHIFT_OUT always drives gpio 0), gpio 1 = SCLK, gpio 2 = CS,
# gpio_in 3 = MISO.
# Mode 0: SCLK idles low, both sides change their data line while SCLK is
# low and sample the other's on the rising edge. CS is active low and frames
# the eight clocks.
#
# This is spi_tx_lsb.asm with every `SET 1, 1 [3]` replaced by
# `SHIFT_IN 3, 1, 1 [3]`: the same rising edge of SCLK now also samples MISO
# into the input shift register. Still two instructions and 8 cycles per bit,
# 4 low, 4 high. After the frame in_shift_reg holds the slave's byte in
# normal order: with shift_dir 0 each sample lands in bit 7 and the register
# shifts right, so the first bit sampled ends up in bit 0. There is no PUSH
# yet; the test bench reads the register directly.
# spi_duplex_msb.asm is this same program with CONFIG shift_dir, 1.

        CONFIG shift_dir, 0 # LSB first (also the reset value), for SHIFT_OUT and SHIFT_IN alike
        SET 1, 0            # SCLK idle low
        PULL 2, 0 [3]       # shift_reg = byte to send (stalls here while the FIFO is empty)
                            # and CS low on the edge the byte arrives: start of frame

        SHIFT_OUT 1, 0 [3]      # bit 0: MOSI = next bit, SCLK low
        SHIFT_IN 3, 1, 1 [3]    #        SCLK high, both sides sample
        SHIFT_OUT 1, 0 [3]      # bit 1
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 2
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 3
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 4
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 5
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 6
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 7
        SHIFT_IN 3, 1, 1 [3]

        SET 1, 0 [3]        # clock back to idle low
        SET 2, 1            # CS high: end of frame
