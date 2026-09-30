# LED chaser: gpio 0, 1, 2, 3 high one at a time, round and round, no host.
# On the PYNQ-Z2 the four pads are also LD0..LD3. A step is two SETs and a
# wait of 32 x 33 = 1056 clocks, NOP [31] run 32 times by REPEAT (no nesting,
# so this is the longest one word can wait), 1058 clocks in all, 1059 for
# the last with its JMP: at CLKDIV 100000 on a 100 MHz FCLK the core runs
# at 1 kHz and each LED is on for about a second.

        SET 1, 0            # every pad is high out of reset: all off but gpio 0
        SET 2, 0
        SET 3, 0
loop:   SET 3, 0            # step 0: LD3 off, LD0 on
        SET 0, 1
w0:     NOP [31]
        REPEAT 32, w0
        SET 0, 0            # step 1
        SET 1, 1
w1:     NOP [31]
        REPEAT 32, w1
        SET 1, 0            # step 2
        SET 2, 1
w2:     NOP [31]
        REPEAT 32, w2
        SET 2, 0            # step 3
        SET 3, 1
w3:     NOP [31]
        REPEAT 32, w3
        JMP loop
