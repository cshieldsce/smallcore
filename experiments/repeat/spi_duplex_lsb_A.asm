# programs/spi_duplex_lsb.asm with REPEAT: 9 words for 22.
        CONFIG open_drain23, 2  # MISO is a pad we listen on: pin 3 open-drain, released
        CONFIG shift_dir, 0     # LSB first, for both shift registers
        SET 1, 0            # SCLK idle low
        PULL 2, 0 [3]       # shift_reg = the byte (stalls while the FIFO is empty), CS low
bit:    SHIFT_OUT 1, 0 [3]      # a bit: MOSI = next bit, SCLK low
        SHIFT_IN 3, 1, 1 [2]    #        SCLK high, both sides sample, 3 cycles, and
        REPEAT 8, bit           #        the 4th: eight bits
        SET 1, 0 [3]        # SCLK low
        PUSH 2, 1           # rx_fifo <- the slave's byte, CS high
