# CAN receiver, RX1 and RX2: the SOF's edge, then the bits as they are. One
# bus pin, gpio 0 open-drain and let go, the bus read back on gpio_in 0; no
# clock line: a bit is 8 cycles, and the receiver takes the level the bus
# held through its sixth (75%, a CAN sample point), read by a SHIFT_IN on
# the seventh. WAIT is the synchronizer: it issues on the first clock the
# bus is dominant, the SOF's edge, and every sample is counted from there.
# 48 bits, six bytes to the host, the SOF bit 7 of the first, stuff bits and
# all: the host's to destuff. Then halted, whether the frame is over or not:
# nothing here can know where it ends, since the DLC is inside the data the
# stuff bits move and the receiver counts raw bits. 13 words.

        CONFIG open_drain01, 1  # CAN_RX open-drain, the reset 1 let go: listening
        CONFIG shift_dir, 1     # MSB first: a sample enters at bit 0 and moves up, so the first of eight ends as bit 7
        WAIT 0, 0 [4]           # the SOF's edge: issues on the first clock the bus is dominant, holds through its fifth
byte:   SHIFT_IN 0 [7]          # the seventh clock, the level through the sixth; held eight: the next bit's seventh follows
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [7]
        SHIFT_IN 0 [5]          # the eighth bit, held six, and
        PUSH                    # the byte to the host, and
        REPEAT 6, byte          # the eighth clock: six bytes, then halted
