# SPI mode 0 master full duplex, one byte each way, MSB first, 8 cycles per bit.
# gpio 0 = MOSI, 1 = SCLK, 2 = CS, gpio_in 3 = MISO.
# spi_tx_msb.asm with SHIFT_IN 3, 1, 1 raising SCLK and sampling MISO on the same
# edge instead of SET 1, 1, and PUSH 2, 1 moving the byte to the RX FIFO on
# the edge that raises CS. Receiving costs no instructions and no cycles.

        CONFIG shift_dir, 1 # MSB first, for both shift registers
        SET 1, 0            # SCLK idle low
        PULL 2, 0 [3]       # shift_reg = the byte (stalls while the FIFO is empty),
                            # CS low on the edge it arrives: start of frame

        SHIFT_OUT 1, 0 [3]      # bit 7: MOSI = next bit, SCLK low
        SHIFT_IN 3, 1, 1 [3]    #        SCLK high, both sides sample
        SHIFT_OUT 1, 0 [3]      # bit 6
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 5
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 4
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 3
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 2
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 1
        SHIFT_IN 3, 1, 1 [3]
        SHIFT_OUT 1, 0 [3]      # bit 0
        SHIFT_IN 3, 1, 1 [3]

        SET 1, 0 [3]        # clock back to idle low
        PUSH 2, 1           # rx_fifo <- in_shift_reg, CS high: end of frame
