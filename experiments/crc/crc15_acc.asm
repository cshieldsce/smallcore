# CRC-15 on candidate Acc, the accumulator: the polynomial from the host,
# left-aligned, low byte first; four host bytes out on pin 0 MSB first and
# back through the pad into ACC_IN, the spec's register in the direct form;
# then the CRC out on pin 1 MSB first, ACC_OUT, one bit per run of the `crc` body. 23 words, 8 distinct. Written by gen.py.

CONFIG shift_dir, 1             # MSB first
PULL                            # the polynomial's low byte
ACC_LOAD
PULL                            # its high byte
ACC_LOAD                        # poly = 0x4599 << 1
PULL                            # byte 0
b0: SHIFT_OUT                   # the data bit onto pin 0
ACC_IN 0                        # and back into the accumulator: f = acc[15] ^ in
REPEAT 8, b0
PULL                            # byte 1
b1: SHIFT_OUT                   # the data bit onto pin 0
ACC_IN 0                        # and back into the accumulator: f = acc[15] ^ in
REPEAT 8, b1
PULL                            # byte 2
b2: SHIFT_OUT                   # the data bit onto pin 0
ACC_IN 0                        # and back into the accumulator: f = acc[15] ^ in
REPEAT 8, b2
PULL                            # byte 3
b3: SHIFT_OUT                   # the data bit onto pin 0
ACC_IN 0                        # and back into the accumulator: f = acc[15] ^ in
REPEAT 8, b3
crc: ACC_OUT 1                  # the CRC's top bit onto pin 1, the accumulator shifted
REPEAT 15, crc                  # halted
