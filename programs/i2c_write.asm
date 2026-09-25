# I2C master, one byte from the TX FIFO, MSB first, 8 cycles per bit.
# gpio 0 = SDA (the shift pin), gpio 1 = SCL. gpio_in 0 = SDA, gpio_in 1 =
# SCL, the lines as the bus holds them. The bus is open-drain and so are the
# two pins (open_drain 0b0011): a 1 on either lets go and leaves the line to
# its pull-up, a 0 pulls it low.
# START: SDA falls while SCL is high, on the edge the byte arrives. Each bit:
# SCL falls, SDA changes two cycles later (hold), SCL rises two cycles after
# that (setup) and the slave samples while it is high. The ninth clock is the
# slave's: the master lets go of SDA, raises SCL and samples SDA on that
# edge, 0 = ACK, and PUSHes the sample as it drops SCL. STOP: SDA rises while
# SCL is high. Both lines rest high.

        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the byte arrives: SDA low while SCL is high (stalls while the FIFO is empty)

        SET 1, 0 [1]            # bit 7: SCL low, SDA holds
        SHIFT_OUT [1]           #        SDA = the bit, setup
        SET 1, 1 [3]            #        SCL high: the slave samples
        SET 1, 0 [1]            # bit 6
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 5
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 4
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 3
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 2
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 1
        SHIFT_OUT [1]
        SET 1, 1 [3]
        SET 1, 0 [1]            # bit 0
        SHIFT_OUT [1]
        SET 1, 1 [3]

        SET 1, 0 [1]            # ACK: SCL low, the slave takes SDA
        SET 0, 1 [1]            #      let go of SDA
        SHIFT_IN 0, 1, 1 [3]    #      SCL high and sample SDA on that edge: 0 = ACK, 1 = NACK
        PUSH 1, 0 [1]           #      SCL low and the sample to the host; the slave lets go of SDA
        SET 0, 0 [1]            # STOP: SDA low while SCL is low
        SET 1, 1 [1]            #       SCL high
        SET 0, 1 [3]            #       SDA rises while SCL is high: bus free
