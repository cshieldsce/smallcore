# programs/i2c_write_stretch.asm with REPEAT, the cell rotated as in
# i2c_write_A.asm: the WAIT is inside the body and stalls there while the
# slave stretches; the count waits with it. 18 words for 45.
        CONFIG open_drain01, 3  # SDA and SCL open-drain: a 1 lets go
        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the byte arrives: SDA low while SCL is high
        SET 1, 0 [1]            # bit 7: SCL low, SDA holds
bit:    SHIFT_OUT [1]           # a bit:  SDA = the bit, setup
        SET 1, 1                #         let go of SCL
        WAIT 1, 1 [2]           #         SCL is high (the slave may hold it low first): the slave samples
        SET 1, 0                #         SCL low for 1 cycle, and
        REPEAT 8, bit           #         the 2nd: eight bits
        SET 0, 1 [1]            # ACK clock: let go of SDA
        SET 1, 1                #            let go of SCL
        WAIT 1, 1               #            SCL is high
        SHIFT_IN 0 [1]          #            sample SDA: 0 is the slave's ACK
        PUSH 1, 0 [1]           #            SCL low; the ACK bit to the host
        SET 0, 0 [1]            # STOP: SDA low
        SET 1, 1                #       let go of SCL
        WAIT 1, 1               #       SCL is high
        SET 0, 1 [3]            #       SDA high while SCL is high
