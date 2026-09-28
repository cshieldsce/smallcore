# programs/i2c_write.asm with REPEAT: the bit cell rotated to start at the
# SHIFT_OUT so the clock's drop, which the byte's first bit has before it and
# the last has after it, is the body's last word and gives the REPEAT its
# cycle. 14 words for 34.
        CONFIG open_drain01, 3  # SDA and SCL open-drain: a 1 lets go
        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the byte arrives: SDA low while SCL is high (stalls while the FIFO is empty)
        SET 1, 0 [1]            # bit 7: SCL low, SDA holds
bit:    SHIFT_OUT [1]           # a bit:  SDA = the bit, setup
        SET 1, 1 [3]            #         SCL high: the slave samples
        SET 1, 0                #         SCL low for 1 cycle, and
        REPEAT 8, bit           #         the 2nd: eight bits
        SET 0, 1 [1]            # ACK clock: let go of SDA
        SHIFT_IN 0, 1, 1 [3]    #            SCL high, sample SDA: 0 is the slave's ACK
        PUSH 1, 0 [1]           #            SCL low; the ACK bit to the host
        SET 0, 0 [1]            # STOP: SDA low
        SET 1, 1 [1]            #       SCL high
        SET 0, 1 [3]            #       SDA high while SCL is high
