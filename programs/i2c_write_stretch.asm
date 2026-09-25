# I2C master, one byte, for a slave that stretches the clock: i2c_write.asm
# with every rise of SCL split in two, SET 1, 1 lets go of the line and WAIT
# 1, 1 holds until the bus really is high. A slave keeps SCL low after a
# falling edge for as long as it needs; the high phase is timed from the
# rise that follows, so the transfer is as long as the slave makes it and
# not a cycle longer. With a slave that never stretches, the same waveform
# as i2c_write.asm, cycle for cycle, for 11 more words.
# The ACK sample moves off the rising edge: SHIFT_IN comes after the WAIT,
# two cycles into the high phase. The WAIT cannot let go of SCL itself: its
# side effect lands on the edge it issues, and it issues once SCL is high.

        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the byte arrives: SDA low while SCL is high

        SET 1, 0 [1]            # bit 7: SCL low, SDA holds
        SHIFT_OUT [1]           #        SDA = the bit, setup
        SET 1, 1                #        let go of SCL
        WAIT 1, 1 [2]           #        SCL is high (the slave may hold it low first): the slave samples
        SET 1, 0 [1]            # bit 6
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 5
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 4
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 3
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 2
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 1
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]
        SET 1, 0 [1]            # bit 0
        SHIFT_OUT [1]
        SET 1, 1
        WAIT 1, 1 [2]

        SET 1, 0 [1]            # ACK: SCL low, the slave takes SDA
        SET 0, 1 [1]            #      let go of SDA
        SET 1, 1                #      let go of SCL
        WAIT 1, 1               #      SCL is high
        SHIFT_IN 0 [1]          #      sample SDA: 0 = ACK, 1 = NACK
        PUSH 1, 0 [1]           #      SCL low and the sample to the host; the slave lets go of SDA
        SET 0, 0 [1]            # STOP: SDA low while SCL is low
        SET 1, 1                #       let go of SCL
        WAIT 1, 1               #       SCL is high
        SET 0, 1 [3]            #       SDA rises while SCL is high: bus free
