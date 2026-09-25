# I2C master write: an address byte and a data byte from the TX FIFO, the
# smallest whole transaction. i2c_write.asm's byte twice inside one START and
# STOP; the second byte's PULL takes the place of the first SCL drop.
# After each ACK clock the sample, 0 = ACK, is PUSHed to the host. A NACK on
# the address byte means no slave answered and the spec asks for a STOP next;
# this program clocks the data byte out anyway, see tests/test_i2c.py.

        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the address byte arrives: SDA low while SCL is high

        SET 1, 0 [1]            # address bit 7: SCL low, SDA holds
        SHIFT_OUT [1]           #                SDA = the bit, setup
        SET 1, 1 [3]            #                SCL high: the slave samples
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
        SET 1, 0 [1]            # bit 0: the write bit
        SHIFT_OUT [1]
        SET 1, 1 [3]

        SET 1, 0 [1]            # ACK: SCL low, the slave takes SDA
        SET 0, 1 [1]            #      let go of SDA
        SHIFT_IN 0, 1, 1 [3]    #      SCL high and sample SDA on that edge: 0 = ACK, 1 = NACK
        PUSH 1, 0 [1]           #      SCL low and the sample to the host; the slave lets go of SDA

        PULL [1]                # data bit 7: shift_reg = the data byte, SCL low (stalls while the FIFO is empty)
        SHIFT_OUT [1]           #             SDA = the bit, setup
        SET 1, 1 [3]            #             SCL high: the slave samples
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
        SHIFT_IN 0, 1, 1 [3]    #      SCL high and sample SDA on that edge
        PUSH 1, 0 [1]           #      SCL low and the sample to the host; the slave lets go of SDA
        SET 0, 0 [1]            # STOP: SDA low while SCL is low
        SET 1, 1 [1]            #       SCL high
        SET 0, 1 [3]            #       SDA rises while SCL is high: bus free
