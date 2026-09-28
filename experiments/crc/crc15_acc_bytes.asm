# CRC-15 on candidate Acc, the accumulator: the polynomial from the host,
# left-aligned, low byte first; four host bytes out on pin 0 MSB first and
# back through the pad into ACC_IN, the spec's register in the direct form;
# then the CRC to the host in two bytes, low first, left-aligned. 23 words, 7 distinct. Written by gen.py.

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
ACC_PUSH                        # {CRC[6:0], 0} to the host
ACC_PUSH                        # CRC[14:7]; halted
