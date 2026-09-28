# programs/i2c_write_addr_data.asm with REPEAT: the address byte and the data
# byte each a rotated cell eight times, the ACK decision between them as it
# was. 24 words for 64.
        CONFIG open_drain01, 3  # SDA and SCL open-drain: a 1 lets go
        CONFIG shift_dir, 1     # MSB first
        PULL 0, 0 [3]           # START as the address arrives: SDA low while SCL is high
        SET 1, 0 [1]            # bit 7: SCL low, SDA holds
abit:   SHIFT_OUT [1]           # an address bit: SDA = the bit, setup
        SET 1, 1 [3]            #                 SCL high: the slave samples
        SET 1, 0                #                 SCL low for 1 cycle, and
        REPEAT 8, abit          #                 the 2nd: eight bits
        SET 0, 1 [1]            # ACK clock: let go of SDA
        SHIFT_IN 0, 1, 1 [3]    #            SCL high, sample SDA: 0 is the slave's ACK
        PUSH 1, 0               #            SCL low; the ACK bit to the host
        SKIP 0, 0               # ACK?  step over the JMP
        JMP stop                # NACK: stop
        PULL [1]                # the data byte (stalls while the FIFO is empty), SCL low
dbit:   SHIFT_OUT [1]           # a data bit: SDA = the bit, setup
        SET 1, 1 [3]            #             SCL high: the slave samples
        SET 1, 0                #             SCL low for 1 cycle, and
        REPEAT 8, dbit          #             the 2nd: eight bits
        SET 0, 1 [1]            # ACK clock: let go of SDA
        SHIFT_IN 0, 1, 1 [3]    #            SCL high, sample SDA
        PUSH 1, 0 [1]           #            SCL low; the ACK bit to the host
stop:   SET 0, 0 [1]            # STOP: SDA low
        SET 1, 1 [1]            #       SCL high
        SET 0, 1 [3]            #       SDA high while SCL is high
