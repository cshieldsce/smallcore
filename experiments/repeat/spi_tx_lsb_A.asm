# programs/spi_tx_lsb.asm with REPEAT: 8 words for 21.
        CONFIG shift_dir, 0 # LSB first (the reset value)
        SET 1, 0            # SCLK idle low (every pin resets high)
        PULL 2, 0 [3]       # shift_reg = the byte (stalls while the FIFO is empty), CS low
bit:    SHIFT_OUT 1, 0 [3]  # a bit: MOSI = next bit, SCLK low
        SET 1, 1 [2]        #        SCLK high for 3 cycles, the slave samples, and
        REPEAT 8, bit       #        the 4th: eight bits
        SET 1, 0 [3]        # SCLK low
        SET 2, 1            # CS high
